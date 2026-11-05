from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework import generics, status
from rest_framework.exceptions import APIException
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import DjMixJob, DjRenderJob, Genre, Song, Stem, VoiceCloneJob, VoiceProfile
from .serializers import (
    DjMixJobCreateSerializer,
    DjMixJobSerializer,
    DjRenderJobCreateSerializer,
    DjRenderJobSerializer,
    GenerateSongSerializer,
    GenreSerializer,
    SongSerializer,
    StemSerializer,
    VoiceCloneJobCreateSerializer,
    VoiceCloneJobSerializer,
    VoiceProfileSerializer,
)
from .tasks import (
    analyze_song_task,
    clone_vocals_task,
    generate_song_task,
    mix_tracks_task,
    process_audio_task,
    render_final_song_task,
    split_song_stems_task,
)


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


class AnalyzeSongView(APIView):
    """Queue BPM/key/cue-point analysis for a song's audio."""

    def post(self, request, pk):
        song = get_object_or_404(Song, pk=pk, user=request.user)
        if not song.audio_file:
            return Response({"detail": "Song has no audio to analyze yet."}, status=status.HTTP_409_CONFLICT)
        try:
            analyze_song_task.delay(song.pk)
        except Exception as exc:
            raise GenerationQueueUnavailable() from exc
        return Response({"detail": "Analysis queued."}, status=status.HTTP_202_ACCEPTED)


class MasterSongView(APIView):
    """Queue the mix-and-master pipeline (gain staging, sidechain, -14 LUFS)."""

    def post(self, request, pk):
        song = get_object_or_404(Song, pk=pk, user=request.user)
        if not song.audio_file and not song.stems.exists():
            return Response({"detail": "Song has no audio or stems to master."}, status=status.HTTP_409_CONFLICT)
        try:
            render_final_song_task.delay(song.pk)
        except Exception as exc:
            raise GenerationQueueUnavailable() from exc
        return Response({"detail": "Mastering queued."}, status=status.HTTP_202_ACCEPTED)


class SongStemListView(generics.ListAPIView):
    serializer_class = StemSerializer

    def get_queryset(self):
        return Stem.objects.filter(song_id=self.kwargs["pk"], song__user=self.request.user).order_by("kind")


class SongStemAutoSplitView(APIView):
    """Queue automatic stem separation (vocals / bass / drums / melody)."""

    def post(self, request, pk):
        song = get_object_or_404(Song, pk=pk, user=request.user)
        if not song.audio_file:
            return Response({"detail": "Song has no audio to split yet."}, status=status.HTTP_409_CONFLICT)
        try:
            split_song_stems_task.delay(song.pk)
        except Exception as exc:
            raise GenerationQueueUnavailable() from exc
        return Response({"detail": "Stem separation queued."}, status=status.HTTP_202_ACCEPTED)


class StemDetailView(generics.RetrieveUpdateDestroyAPIView):
    """Read / mix-state update (mute, solo, volume, pan) / delete a stem."""

    serializer_class = StemSerializer
    http_method_names = ["get", "patch", "delete", "head", "options"]

    def get_queryset(self):
        return Stem.objects.filter(song__user=self.request.user).select_related("song")


class DjRenderListCreateView(generics.ListCreateAPIView):
    """GET lists the user's DSP renders; POST queues a new effects-chain render."""

    def get_queryset(self):
        return DjRenderJob.objects.filter(user=self.request.user).select_related("source_song")

    def get_serializer_class(self):
        if self.request.method == "POST":
            return DjRenderJobCreateSerializer
        return DjRenderJobSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            job = serializer.save()
        try:
            process_audio_task.delay(job.pk)
        except Exception as exc:
            DjRenderJob.objects.filter(pk=job.pk).update(
                status=DjRenderJob.Status.FAILED,
                failure_reason="Render queue is temporarily unavailable.",
            )
            raise GenerationQueueUnavailable() from exc
        return Response(DjRenderJobSerializer(job, context={"request": request}).data, status=status.HTTP_202_ACCEPTED)


class DjRenderDetailView(generics.RetrieveAPIView):
    serializer_class = DjRenderJobSerializer

    def get_queryset(self):
        return DjRenderJob.objects.filter(user=self.request.user)


class DjMixListCreateView(generics.ListCreateAPIView):
    """GET lists the user's mixes; POST queues an automated mashup/transition."""

    def get_queryset(self):
        return DjMixJob.objects.filter(user=self.request.user).select_related("track_a", "track_b")

    def get_serializer_class(self):
        if self.request.method == "POST":
            return DjMixJobCreateSerializer
        return DjMixJobSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            job = serializer.save()
        try:
            mix_tracks_task.delay(job.pk)
        except Exception as exc:
            DjMixJob.objects.filter(pk=job.pk).update(
                status=DjMixJob.Status.FAILED,
                failure_reason="Mix queue is temporarily unavailable.",
            )
            raise GenerationQueueUnavailable() from exc
        return Response(DjMixJobSerializer(job, context={"request": request}).data, status=status.HTTP_202_ACCEPTED)


class DjMixDetailView(generics.RetrieveAPIView):
    serializer_class = DjMixJobSerializer

    def get_queryset(self):
        return DjMixJob.objects.filter(user=self.request.user).select_related("track_a", "track_b")


class VoiceListView(generics.ListAPIView):
    """Active vocal profiles (male / female / child / choirs / duet)."""

    queryset = VoiceProfile.objects.filter(is_active=True)
    serializer_class = VoiceProfileSerializer


class VoiceCloneJobListCreateView(generics.ListCreateAPIView):
    """GET lists the user's voice-clone jobs; POST queues a vocal conversion."""

    def get_queryset(self):
        return VoiceCloneJob.objects.filter(user=self.request.user).select_related("voice", "source_song")

    def get_serializer_class(self):
        if self.request.method == "POST":
            return VoiceCloneJobCreateSerializer
        return VoiceCloneJobSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            job = serializer.save()
        try:
            clone_vocals_task.delay(job.pk)
        except Exception as exc:
            VoiceCloneJob.objects.filter(pk=job.pk).update(
                status=VoiceCloneJob.Status.FAILED,
                failure_reason="Voice-clone queue is temporarily unavailable.",
            )
            raise GenerationQueueUnavailable() from exc
        return Response(VoiceCloneJobSerializer(job, context={"request": request}).data, status=status.HTTP_202_ACCEPTED)


class VoiceCloneJobDetailView(generics.RetrieveAPIView):
    serializer_class = VoiceCloneJobSerializer

    def get_queryset(self):
        return VoiceCloneJob.objects.filter(user=self.request.user).select_related("voice", "source_song")
