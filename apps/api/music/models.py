from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models


class User(AbstractUser):
    pass


class Genre(models.Model):
    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=100, unique=True)
    category = models.CharField(max_length=100, blank=True)
    description = models.TextField(blank=True)
    tempo_min_bpm = models.PositiveSmallIntegerField(null=True, blank=True)
    tempo_max_bpm = models.PositiveSmallIntegerField(null=True, blank=True)
    default_key = models.CharField(max_length=16, blank=True)
    typical_instrumentation = models.JSONField(default=list, blank=True)
    style_prompt = models.TextField(blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Instrument(models.Model):
    class Category(models.TextChoices):
        TRADITIONAL = "traditional", "Traditional"
        MODERN = "modern", "Modern"

    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=100, unique=True)
    category = models.CharField(max_length=16, choices=Category.choices)
    spectral_tags = models.JSONField(default=list, blank=True)
    prompt_description = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["category", "name"]

    def __str__(self):
        return self.name


class Song(models.Model):
    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        PROCESSING = "PROCESSING", "Processing"
        COMPLETED = "COMPLETED", "Completed"
        FAILED = "FAILED", "Failed"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="songs")
    title = models.CharField(max_length=200)
    user_prompt = models.TextField()
    compiled_ai_prompt = models.TextField()
    generated_lyrics = models.TextField(blank=True)
    language = models.CharField(max_length=16, default="gikuyu")
    mood = models.CharField(max_length=80, default="joyful")
    genre = models.ForeignKey(Genre, on_delete=models.PROTECT, related_name="songs")
    chosen_instruments = models.ManyToManyField(Instrument, blank=True, related_name="songs")
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING, db_index=True)
    audio_file = models.FileField(upload_to="generated/%Y/%m/%d/", blank=True)
    duration = models.PositiveSmallIntegerField(default=120, validators=[MinValueValidator(30), MaxValueValidator(300)])
    tempo_bpm = models.PositiveSmallIntegerField(null=True, blank=True, validators=[MinValueValidator(30), MaxValueValidator(300)])
    musical_key = models.CharField(max_length=16, blank=True, help_text='Detected key, e.g. "A minor"')
    camelot = models.CharField(max_length=4, blank=True, help_text="Camelot wheel code for harmonic mixing, e.g. 8A")
    cue_points = models.JSONField(default=list, blank=True, help_text="Auto-detected DJ cue markers")
    audio_waveform_data = models.JSONField(default=list, blank=True)
    failure_reason = models.TextField(blank=True)
    generation_task_id = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["user", "status", "-created_at"])]

    def __str__(self):
        return f"{self.title} ({self.status})"


class Stem(models.Model):
    """An isolated stem track (vocals / bass / drums / melody) of a Song.

    Stems are either produced by the AI backend (see split_song_stems_task) or
    uploaded directly. volume / pan / mute / solo hold the deck mix state.
    """

    class Kind(models.TextChoices):
        VOCALS = "vocals", "Vocals"
        BASS = "bass", "Bass"
        DRUMS = "drums", "Drums"
        MELODY = "melody", "Melody / Other"

    song = models.ForeignKey(Song, on_delete=models.CASCADE, related_name="stems")
    kind = models.CharField(max_length=16, choices=Kind.choices)
    audio_file = models.FileField(upload_to="stems/%Y/%m/%d/")
    volume = models.FloatField(default=1.0, validators=[MinValueValidator(0.0), MaxValueValidator(2.0)])
    pan = models.FloatField(default=0.0, validators=[MinValueValidator(-1.0), MaxValueValidator(1.0)])
    is_muted = models.BooleanField(default=False)
    is_solo = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["song", "kind"]

    def __str__(self):
        return f"{self.song_id}:{self.kind}"


class DjRenderJob(models.Model):
    """Server-side DSP render: applies an effects chain to a Song's audio."""

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        PROCESSING = "PROCESSING", "Processing"
        COMPLETED = "COMPLETED", "Completed"
        FAILED = "FAILED", "Failed"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="dj_renders")
    source_song = models.ForeignKey(Song, on_delete=models.CASCADE, related_name="dj_renders")
    operations = models.JSONField(default=list, help_text="Ordered DSP chain, see dj_tools.run_chain")
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING, db_index=True)
    output_file = models.FileField(upload_to="dj/renders/%Y/%m/%d/", blank=True)
    failure_reason = models.TextField(blank=True)
    task_id = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"render:{self.pk} song={self.source_song_id} ({self.status})"


class DjMixJob(models.Model):
    """Automated mashup / transition between two tracks."""

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        PROCESSING = "PROCESSING", "Processing"
        COMPLETED = "COMPLETED", "Completed"
        FAILED = "FAILED", "Failed"

    class Transition(models.TextChoices):
        CUT = "cut", "Cut"
        CROSSFADE = "crossfade", "Smooth Crossfade"
        DROP_SWAP = "drop_swap", "Drop Swap"
        ECHO_OUT = "echo_out", "Echo Out"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="dj_mixes")
    track_a = models.ForeignKey(Song, on_delete=models.CASCADE, related_name="mixes_as_a")
    track_b = models.ForeignKey(Song, on_delete=models.CASCADE, related_name="mixes_as_b")
    transition = models.CharField(max_length=16, choices=Transition.choices, default=Transition.CROSSFADE)
    transition_bars = models.PositiveSmallIntegerField(default=8, validators=[MinValueValidator(1), MaxValueValidator(32)])
    match_tempo = models.BooleanField(default=True, help_text="Time-stretch track B onto track A's BPM")
    match_key = models.BooleanField(default=True, help_text="Transpose track B onto track A's key")
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING, db_index=True)
    output_file = models.FileField(upload_to="dj/mixes/%Y/%m/%d/", blank=True)
    mix_waveform_data = models.JSONField(default=list, blank=True)
    analysis = models.JSONField(default=dict, blank=True, help_text="BPM/key analysis of both tracks")
    failure_reason = models.TextField(blank=True)
    task_id = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["user", "status", "-created_at"])]

    def __str__(self):
        return f"mix:{self.pk} {self.track_a_id}->{self.track_b_id} ({self.status})"