from django.core.management.base import BaseCommand

from music.models import Genre, Instrument


GENRES = [
    {
        "name": "Mũgithi",
        "slug": "mugithi",
        "category": "Kikuyu popular",
        "description": "Acoustic single-guitar style with a fast live rhythm and continuous dance sequence.",
        "tempo_min_bpm": 110,
        "tempo_max_bpm": 145,
        "default_key": "G",
        "typical_instrumentation": ["Acoustic steel-string guitar", "Walking bass guitar", "Shakers"],
    },
    {
        "name": "Kikuyu Benga",
        "slug": "benga",
        "category": "Kikuyu popular",
        "description": "Fast 4/4 dance music with interlocking guitars, driving bass, and syncopated hi-hats.",
        "tempo_min_bpm": 110,
        "tempo_max_bpm": 150,
        "default_key": "A",
        "typical_instrumentation": ["Electric rhythm guitar", "Electric lead guitar", "Bass guitar", "Drum kit"],
    },
    {
        "name": "Gospel / Kĩrooko",
        "slug": "gospel",
        "category": "Gospel",
        "description": "Praise and worship, Pentecostal choir arrangements, energetic praise dance, or reflective worship.",
        "tempo_min_bpm": 60,
        "tempo_max_bpm": 145,
        "default_key": "C",
        "typical_instrumentation": ["Choir", "Keyboard", "Drum kit", "Bass guitar"],
    },
    {
        "name": "Mwomboko",
        "slug": "mwomboko",
        "category": "Traditional dance",
        "description": "Traditional 3/4 or 6/8 accordion dance rhythm with metal shaker.",
        "tempo_min_bpm": 85,
        "tempo_max_bpm": 125,
        "default_key": "D",
        "typical_instrumentation": ["Accordion", "Shakers", "Bass guitar"],
    },
    {
        "name": "Kikuyu Afro-Pop / Urban Kikuyu",
        "slug": "afro-pop",
        "category": "Contemporary fusion",
        "description": "Modern Gĩkũyũ lyrics blended with Amapiano, Afrobeat, or Gengetone elements.",
        "tempo_min_bpm": 90,
        "tempo_max_bpm": 130,
        "default_key": "C",
        "typical_instrumentation": ["Synthesizers", "Drum kit", "Bass guitar", "Electric guitar"],
    },
    {
        "name": "Acoustic Folk / Kĩmũrĩ",
        "slug": "acoustic-folk",
        "category": "Traditional folk",
        "description": "Njanama, Kĩbaata, and Mũthũngũci-influenced acoustic storytelling with call-and-response.",
        "tempo_min_bpm": 65,
        "tempo_max_bpm": 115,
        "default_key": "G",
        "typical_instrumentation": ["Acoustic guitar", "Wandĩndĩ", "Kĩgamba"],
    },
    {
        "name": "Traditional Chants",
        "slug": "traditional-chants",
        "category": "Traditional folk",
        "description": "Njanama, Kĩbaata, and Mũthũngũci traditional chants and communal responses.",
        "tempo_min_bpm": 65,
        "tempo_max_bpm": 135,
        "default_key": "G",
        "typical_instrumentation": ["Wandĩndĩ", "Kĩgamba", "Coro", "Mũgũgũmũ"],
    },
]

INSTRUMENTS = [
    ("Wandĩndĩ", "wandindi", Instrument.Category.TRADITIONAL, ["bowed", "midrange"]),
    ("Kĩgamba", "kigamba", Instrument.Category.TRADITIONAL, ["shaker", "high-frequency"]),
    ("Coro", "coro", Instrument.Category.TRADITIONAL, ["horn", "resonant"]),
    ("Ndũmũ flute", "ndumu-flute", Instrument.Category.TRADITIONAL, ["flute", "airy"]),
    ("Mũtũrĩrũ flute", "muturiru-flute", Instrument.Category.TRADITIONAL, ["flute", "airy"]),
    ("Mũgũgũmũ", "mugugumu", Instrument.Category.TRADITIONAL, ["percussion", "low-frequency"]),
    ("Acoustic Steel-String Guitar", "acoustic-steel-string-guitar", Instrument.Category.MODERN, ["plucked", "bright"]),
    ("Electric Rhythm Guitar", "electric-rhythm-guitar", Instrument.Category.MODERN, ["electric", "midrange"]),
    ("Electric Lead Guitar", "electric-lead-guitar", Instrument.Category.MODERN, ["electric", "lead"]),
    ("Slap Bass Guitar", "slap-bass", Instrument.Category.MODERN, ["bass", "percussive"]),
    ("Walking Bass Guitar", "walking-bass", Instrument.Category.MODERN, ["bass", "groove"]),
    ("Accordion", "accordion", Instrument.Category.MODERN, ["reed", "melodic"]),
    ("Brass Section", "brass-section", Instrument.Category.MODERN, ["brass", "bright"]),
    ("Synthesizers", "synthesizers", Instrument.Category.MODERN, ["electronic", "synth"]),
    ("Drum Kit", "drum-kit", Instrument.Category.MODERN, ["percussion", "rhythmic"]),
    ("Shakers / Tambourine", "shakers-tambourine", Instrument.Category.MODERN, ["shaker", "high-frequency"]),
]


class Command(BaseCommand):
    help = "Create or update the built-in Kikuyu genre and instrument catalog."

    def handle(self, *args, **options):
        for genre in GENRES:
            Genre.objects.update_or_create(slug=genre["slug"], defaults=genre)
        for name, slug, category, spectral_tags in INSTRUMENTS:
            Instrument.objects.update_or_create(
                slug=slug,
                defaults={
                    "name": name,
                    "category": category,
                    "spectral_tags": spectral_tags,
                    "prompt_description": name,
                },
            )
        self.stdout.write(self.style.SUCCESS(f"Loaded {len(GENRES)} genres and {len(INSTRUMENTS)} instruments."))