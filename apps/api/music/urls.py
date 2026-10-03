from django.urls import path

from .views import GenerateSongView, GenreListView, SongDetailView, SongListView

urlpatterns = [
    path("generate/", GenerateSongView.as_view(), name="generate-song"),
    path("songs/", SongListView.as_view(), name="song-list"),
    path("songs/<int:pk>/", SongDetailView.as_view(), name="song-detail"),
    path("genres/", GenreListView.as_view(), name="genre-list"),
]