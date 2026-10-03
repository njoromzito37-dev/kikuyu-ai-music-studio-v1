from rest_framework import serializers

from .models import Genre, Instrument, Song
from .services.prompt_engine import KikuyuPromptEngine


class InstrumentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Instrument
        fields = ("id", "name", "slug", "category", "spectral_tags")


class GenreSerializer(serializers.ModelSerializer):
    class Meta:
        model = Genre
        fields = ("id", "name", "slug", "category", "tempo_min_bpm", "tempo_max_bpm", "default_key", "typical_instrumentation")


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
    audio_url = serializers.SerializerMethodField()

    class Meta:
        model = Song
        fields = (
            "id", "title", "user_prompt", "compiled_ai_prompt", "generated_lyrics", "language", "mood",
            "genre", "chosen_instruments", "status", "audio_url", "duration", "tempo_bpm",
            "audio_waveform_data", "failure_reason", "created_at", "updated_at",
        )
        read_only_fields = fields

    def get_audio_url(self, obj):
        if not obj.audio_file:
            return None
        request = self.context.get("request")
        url = obj.audio_file.url
        return request.build_absolute_uri(url) if request else url