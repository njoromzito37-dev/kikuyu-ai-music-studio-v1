from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import DjMixJob, DjRenderJob, Genre, Instrument, Song, Stem, User, VoiceCloneJob, VoiceProfile


@admin.register(User)
class StudioUserAdmin(UserAdmin):
    pass


@admin.register(Genre)
class GenreAdmin(admin.ModelAdmin):
    list_display = ("name", "category", "tempo_min_bpm", "tempo_max_bpm")
    prepopulated_fields = {"slug": ("name",)}
    search_fields = ("name", "category")


@admin.register(Instrument)
class InstrumentAdmin(admin.ModelAdmin):
    list_display = ("name", "category")
    prepopulated_fields = {"slug": ("name",)}
    list_filter = ("category",)
    search_fields = ("name",)


@admin.register(Song)
class SongAdmin(admin.ModelAdmin):
    list_display = ("title", "user", "genre", "status", "tempo_bpm", "musical_key", "created_at")
    list_filter = ("status", "genre", "created_at")
    search_fields = ("title", "user__username")
    readonly_fields = ("created_at", "updated_at")


@admin.register(Stem)
class StemAdmin(admin.ModelAdmin):
    list_display = ("song", "kind", "volume", "pan", "is_muted", "is_solo", "updated_at")
    list_filter = ("kind", "is_muted", "is_solo")
    search_fields = ("song__title",)


@admin.register(DjRenderJob)
class DjRenderJobAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "source_song", "status", "created_at")
    list_filter = ("status", "created_at")
    readonly_fields = ("created_at", "updated_at")


@admin.register(DjMixJob)
class DjMixJobAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "track_a", "track_b", "transition", "status", "created_at")
    list_filter = ("status", "transition", "created_at")
    readonly_fields = ("created_at", "updated_at")


@admin.register(VoiceProfile)
class VoiceProfileAdmin(admin.ModelAdmin):
    list_display = ("name", "vocal_type", "language", "is_active")
    prepopulated_fields = {"slug": ("name",)}
    list_filter = ("vocal_type", "is_active")
    search_fields = ("name",)


@admin.register(VoiceCloneJob)
class VoiceCloneJobAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "source_song", "voice", "status", "created_at")
    list_filter = ("status", "created_at")
    readonly_fields = ("created_at", "updated_at")