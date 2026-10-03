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