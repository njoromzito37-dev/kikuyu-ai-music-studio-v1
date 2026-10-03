from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import Genre, Instrument, Song, User


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
    list_display = ("title", "user", "genre", "status", "created_at")
    list_filter = ("status", "genre", "created_at")
    search_fields = ("title", "user__username")
    readonly_fields = ("created_at", "updated_at")