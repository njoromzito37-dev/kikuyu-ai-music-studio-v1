from rest_framework import serializers

from .models import DjMixJob, DjRenderJob, Genre, Instrument, Song, Stem
from .services.prompt_engine import KikuyuPromptEngine


class InstrumentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Instrument
        fields = ("id", "name", "slug", "category", "spectral_tags")


class GenreSerializer(serializers.ModelSerializer):
    class Meta:
        model = Genre
        fields = ("id", "name", "slug", "category", "tempo_min_bpm", "tempo_max_bpm", "default_key", "typical_instrumentation")


class StemSerializer(serializers.ModelSerializer):
    audio_url = serializers.SerializerMethodField()

    class Meta:
        model = Stem
        fields = ("id", "song", "kind", "audio_url", "volume", "pan", "is_muted", "is_solo", "created_at", "updated_at")
        read_only_fields = ("song", "created_at", "updated_at")

    def get_audio_url(self, obj):
        if not obj.audio_file:
            return None
        request = self.context.get("request")
        url = obj.audio_file.url
        return request.build_absolute_uri(url) if request else url


class GenerateSongSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=200)
    prompt = serializers.CharField(max_length=4000)
    lyrics = serializers.CharField(required=False, allow_blank=True, max_length=12000)
    language = serializers.ChoiceField(choices=("gikuyu", "swahili", "english"), default="gikuyu")
    genre = serializers.SlugRelatedField(slug_field="slug", queryset=Genre.objects.all(), required=False)
    mood = serializers.CharField(max_length=80, default="joyful")
    instruments = serializers.PrimaryKeyRelatedField(queryset=Instrument.objects.all(), many=True, required=False)
    duration = serializers.IntegerField(min_value=30, max_value=300, default=120)
    tempo_bpm = serializers.IntegerField(min_value=30, max_value=300, required=False, allow_null=True)

    def validate_prompt(self, value):
        if not value.strip():
            raise serializers.ValidationError("A non-empty prompt is required.")
        return value

    def validate(self, attrs):
        if "genre" not in attrs:
            slug = KikuyuPromptEngine.infer_genre_slug(attrs["prompt"])
            try:
                attrs["genre"] = Genre.objects.get(slug=slug)
            except Genre.DoesNotExist as exc:
                raise serializers.ValidationError({"genre": "No catalog genre matches this prompt; provide a genre slug."}) from exc
        return attrs

    def create(self, validated_data):
        instruments = validated_data.pop("instruments", [])
        prompt = validated_data.pop("prompt")
        lyrics = validated_data.pop("lyrics", "")
        genre = validated_data["genre"]
        if not validated_data.get("title"):
            validated_data["title"] = prompt[:80] or "Untitled Song"
        composition = KikuyuPromptEngine().compose(
            text_prompt=prompt,
            genre=genre,
            instruments=instruments,
            language=validated_data["language"],
            mood=validated_data["mood"],
            lyrics=lyrics,
        )
        song = Song.objects.create(
            user=self.context["request"].user,
            user_prompt=prompt,
            compiled_ai_prompt=composition["compiled_ai_prompt"],
            generated_lyrics=composition["generated_lyrics"],
            **validated_data,
        )
        song.chosen_instruments.set(instruments)
        return song


class SongSerializer(serializers.ModelSerializer):
    genre = GenreSerializer(read_only=True)
    chosen_instruments = InstrumentSerializer(many=True, read_only=True)
    stems = StemSerializer(many=True, read_only=True)
    audio_url = serializers.SerializerMethodField()

    class Meta:
        model = Song
        fields = (
            "id", "title", "user_prompt", "compiled_ai_prompt", "generated_lyrics", "language", "mood",
            "genre", "chosen_instruments", "stems", "status", "audio_url", "duration", "tempo_bpm",
            "musical_key", "camelot", "cue_points",
            "audio_waveform_data", "failure_reason", "created_at", "updated_at",
        )
        read_only_fields = fields

    def get_audio_url(self, obj):
        if not obj.audio_file:
            return None
        request = self.context.get("request")
        url = obj.audio_file.url
        return request.build_absolute_uri(url) if request else url


DJ_ALLOWED_OPERATIONS = frozenset(
    {"time_stretch", "pitch_shift", "eq", "flanger", "reverb", "echo", "delay", "filter_sweep", "filter", "normalize"}
)


def _absolute_file_url(serializer, obj, field_name):
    file_field = getattr(obj, field_name)
    if not file_field:
        return None
    request = serializer.context.get("request")
    url = file_field.url
    return request.build_absolute_uri(url) if request else url


class DjRenderJobSerializer(serializers.ModelSerializer):
    output_url = serializers.SerializerMethodField()

    class Meta:
        model = DjRenderJob
        fields = ("id", "source_song", "operations", "status", "output_url", "failure_reason", "created_at", "updated_at")
        read_only_fields = fields

    def get_output_url(self, obj):
        return _absolute_file_url(self, obj, "output_file")


class DjRenderJobCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = DjRenderJob
        fields = ("source_song", "operations")

    def validate_source_song(self, song):
        if song.user_id != self.context["request"].user.id:
            raise serializers.ValidationError("You can only process your own songs.")
        if not song.audio_file:
            raise serializers.ValidationError("This song has no audio to process yet.")
        return song

    def validate_operations(self, operations):
        if not isinstance(operations, list) or not operations:
            raise serializers.ValidationError("Provide a non-empty list of DSP operations.")
        if len(operations) > 12:
            raise serializers.ValidationError("At most 12 operations per render.")
        for index, operation in enumerate(operations):
            if not isinstance(operation, dict) or operation.get("op") not in DJ_ALLOWED_OPERATIONS:
                allowed = ", ".join(sorted(DJ_ALLOWED_OPERATIONS))
                raise serializers.ValidationError(f"Operation {index} must name one of: {allowed}.")
            for key, value in operation.items():
                if key != "op" and not isinstance(value, (int, float, str, bool)):
                    raise serializers.ValidationError(f"Operation {index} parameter {key!r} must be a number or string.")
        return operations

    def create(self, validated_data):
        return DjRenderJob.objects.create(user=self.context["request"].user, **validated_data)


class DjMixJobSerializer(serializers.ModelSerializer):
    track_a = SongSerializer(read_only=True)
    track_b = SongSerializer(read_only=True)
    output_url = serializers.SerializerMethodField()

    class Meta:
        model = DjMixJob
        fields = (
            "id", "track_a", "track_b", "transition", "transition_bars", "match_tempo", "match_key",
            "status", "output_url", "mix_waveform_data", "analysis", "failure_reason", "created_at", "updated_at",
        )
        read_only_fields = fields

    def get_output_url(self, obj):
        return _absolute_file_url(self, obj, "output_file")


class DjMixJobCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = DjMixJob
        fields = ("track_a", "track_b", "transition", "transition_bars", "match_tempo", "match_key")

    def _validate_ready_track(self, song):
        if song.user_id != self.context["request"].user.id:
            raise serializers.ValidationError("You can only mix your own songs.")
        if song.status != Song.Status.COMPLETED or not song.audio_file:
            raise serializers.ValidationError("Track must be a completed song with audio.")
        return song

    def validate_track_a(self, song):
        return self._validate_ready_track(song)

    def validate_track_b(self, song):
        return self._validate_ready_track(song)

    def validate(self, attrs):
        if attrs["track_a"] == attrs["track_b"]:
            raise serializers.ValidationError({"track_b": "Choose two different tracks to mix."})
        return attrs

    def create(self, validated_data):
        return DjMixJob.objects.create(user=self.context["request"].user, **validated_data)