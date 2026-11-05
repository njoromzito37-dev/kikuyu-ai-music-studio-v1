from django.urls import path

from .views import (
    AnalyzeSongView,
    DjMixDetailView,
    DjMixListCreateView,
    DjRenderDetailView,
    DjRenderListCreateView,
    GenerateSongView,
    GenreListView,
    MasterSongView,
    SongDetailView,
    SongListView,
    SongStemAutoSplitView,
    SongStemListView,
    StemDetailView,
    VoiceCloneJobDetailView,
    VoiceCloneJobListCreateView,
    VoiceListView,
)

urlpatterns = [
    path("generate/", GenerateSongView.as_view(), name="generate-song"),
    path("songs/", SongListView.as_view(), name="song-list"),
    path("songs/<int:pk>/", SongDetailView.as_view(), name="song-detail"),
    path("songs/<int:pk>/analyze/", AnalyzeSongView.as_view(), name="song-analyze"),
    path("songs/<int:pk>/master/", MasterSongView.as_view(), name="song-master"),
    path("songs/<int:pk>/stems/", SongStemListView.as_view(), name="song-stem-list"),
    path("songs/<int:pk>/stems/auto-split/", SongStemAutoSplitView.as_view(), name="song-stem-auto-split"),
    path("stems/<int:pk>/", StemDetailView.as_view(), name="stem-detail"),
    path("dj/process/", DjRenderListCreateView.as_view(), name="dj-render-list-create"),
    path("dj/process/<int:pk>/", DjRenderDetailView.as_view(), name="dj-render-detail"),
    path("dj/mix/", DjMixListCreateView.as_view(), name="dj-mix-list-create"),
    path("dj/mix/<int:pk>/", DjMixDetailView.as_view(), name="dj-mix-detail"),
    path("voices/", VoiceListView.as_view(), name="voice-list"),
    path("voices/clone/", VoiceCloneJobListCreateView.as_view(), name="voice-clone-list-create"),
    path("voices/clone/<int:pk>/", VoiceCloneJobDetailView.as_view(), name="voice-clone-detail"),
    path("genres/", GenreListView.as_view(), name="genre-list"),
]