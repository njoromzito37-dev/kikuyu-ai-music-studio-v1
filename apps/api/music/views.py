from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework import generics, status
from rest_framework.exceptions import APIException
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Genre, Song
from .serializers import GenerateSongSerializer, GenreSerializer, SongSerializer
from .tasks import generate_song_task


class GenerationQueueUnavailable(APIException):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    default_detail = "Generation queue is temporarily unavailable."
    default_code = "generation_queue_unavailable"


class GenerateSongView(APIView):
    def post(self, request):
        serializer = GenerateSongSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            song = serializer.save()
        try:
            generate_song_task.delay(song.pk)
        except Exception as exc:
            Song.objects.filter(pk=song.pk).update(
                status=Song.Status.FAILED,
                failure_reason="Generation queue is temporarily unavailable.",
            )
            raise GenerationQueueUnavailable() from exc
        return Response(SongSerializer(song, context={"request": request}).data, status=status.HTTP_202_ACCEPTED)


class SongListView(generics.ListAPIView):
    serializer_class = SongSerializer

    def get_queryset(self):
        queryset = Song.objects.filter(user=self.request.user).select_related("genre").prefetch_related("chosen_instruments")
        genre_slug = self.request.query_params.get("genre")
        if genre_slug:
            queryset = queryset.filter(genre__slug=genre_slug)
        return queryset


class SongDetailView(generics.RetrieveAPIView):
    serializer_class = SongSerializer

    def get_queryset(self):
        return Song.objects.filter(user=self.request.user).select_related("genre").prefetch_related("chosen_instruments")


class GenreListView(generics.ListAPIView):
    queryset = Genre.objects.all()
    serializer_class = GenreSerializer
