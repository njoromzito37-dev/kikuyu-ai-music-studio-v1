import re
import unicodedata


GENRE_STYLES = {
    "mugithi": "Mũgithi: acoustic single-guitar groove, fast live dance rhythm, continuous dance sequence, communal call-and-response vocals",
    "benga": "Kikuyu Benga: brisk 4/4 pulse, interlocking dual electric guitars, driving bassline, syncopated hi-hats, bright melodic hooks",
    "kikuyu-benga": "Kikuyu Benga: brisk 4/4 pulse, interlocking dual electric guitars, driving bassline, syncopated hi-hats, bright melodic hooks",
    "gospel": "Gospel / Kĩrooko: expressive praise and worship vocals, Pentecostal choir harmonies, energetic praise-dance rhythm or reflective worship dynamics",
    "kirooko": "Gospel / Kĩrooko: expressive praise and worship vocals, Pentecostal choir harmonies, energetic praise-dance rhythm or reflective worship dynamics",
    "mwomboko": "Mwomboko: lilting 3/4 or 6/8 dance meter, accordion melody, crisp metal-shaker rhythm, elegant traditional phrasing",
    "afro-pop": "Kikuyu Afro-Pop / Urban Kikuyu: contemporary Gĩkũyũ vocals fused with Afrobeat, Amapiano, or Gengetone production",
    "urban-kikuyu": "Kikuyu Afro-Pop / Urban Kikuyu: contemporary Gĩkũyũ vocals fused with Afrobeat, Amapiano, or Gengetone production",
    "acoustic-folk": "Acoustic Folk / Kĩmũrĩ: intimate traditional acoustic storytelling, Njanama, Kĩbaata, or Mũthũngũci influence, vocal call-and-response",
    "traditional-chants": "Traditional Chants: Njanama, Kĩbaata, and Mũthũngũci-inspired storytelling, communal call-and-response and organic acoustic textures",
}

GENRE_ALIASES = {
    "mugithi": ("mugithi", "mũgithi"),
    "benga": ("benga",),
    "gospel": ("gospel", "kirooko", "kĩrooko", "worship", "praise", "sifa"),
    "mwomboko": ("mwomboko", "mwomboko"),
    "afro-pop": ("afro-pop", "afropop", "afrobeat", "amapiano", "gengetone", "urban kikuyu"),
    "traditional-chants": ("traditional chant", "traditional chants", "njanama", "kĩbaata", "mũthũngũci"),
    "acoustic-folk": ("acoustic folk", "kimuri", "kĩmũrĩ", "njanama", "kibaata", "kĩbaata", "muthunguci", "mũthũngũci"),
}

INSTRUMENT_PROMPTS = {
    "wandĩndĩ": "Wandĩndĩ (single-string fiddle), expressive bowed lead",
    "kĩgamba": "Kĩgamba (leg rattles / maracas), dry rhythmic shake",
    "coro": "Coro (horn / kudu horn), resonant traditional calls",
    "ndũmũ": "Ndũmũ (traditional flute), airy melodic phrases",
    "mũtũrĩrũ": "Mũtũrĩrũ (traditional flute), airy melodic phrases",
    "mũgũgũmũ": "Mũgũgũmũ (percussion trunk / drum), earthy low percussion",
    "acoustic-steel-string-guitar": "acoustic steel-string guitar",
    "electric-rhythm-guitar": "interlocking electric rhythm guitar",
    "electric-lead-guitar": "bright electric lead guitar",
    "slap-bass": "slap bass guitar",
    "walking-bass": "warm walking bass guitar",
    "accordion": "accordion",
    "brass-section": "brass section",
    "synthesizers": "modern synthesizers",
    "drum-kit": "live drum kit",
    "shakers-tambourine": "shakers and tambourine",
}

LYRIC_TEMPLATES = {
    "gikuyu": "[Verse 1]\n{theme}, ngoro yakwa ĩrĩ na gĩkeno\nTũrĩ hamwe, tũigue rũĩmbo rũrĩa rwega\n\n[Chorus]\nŨcio nĩ wega, tũinage hamwe\nWendo na thayũ, thĩinĩ wa ngoro ciitũ\n\n[Interlude - Guitar Solo]\n\n[Verse 2]\nRũciinĩ rũothe, tũcooke hamwe\n{theme}, rũĩmbo rũitũ rũikarage\n\n[Chorus]\nŨcio nĩ wega, tũinage hamwe\nWendo na thayũ, thĩinĩ wa ngoro ciitũ\n\n[Outro]\nTũinage hamwe, tũinage hamwe",
    "swahili": "[Verse 1]\n{theme}, furaha iko moyoni\nTuko pamoja, tusikie wimbo mzuri\n\n[Chorus]\nTuimbe pamoja, kwa upendo na amani\nTusherehekee maisha, kwa sauti moja\n\n[Interlude - Guitar Solo]\n\n[Verse 2]\nKila siku mpya, tumaini linatuchanua\n{theme}, wimbo wetu utaendelea\n\n[Chorus]\nTuimbe pamoja, kwa upendo na amani\nTusherehekee maisha, kwa sauti moja\n\n[Outro]\nTuimbe pamoja, tuimbe pamoja",
    "english": "[Verse 1]\n{theme}, let the good days find us here\nEvery voice together, every heartbeat clear\n\n[Chorus]\nWe sing as one, we dance as one\nOur story carries on and on\n\n[Interlude - Guitar Solo]\n\n[Verse 2]\nThrough every turning, hope will lead the way\n{theme}, we make a brighter day\n\n[Chorus]\nWe sing as one, we dance as one\nOur story carries on and on\n\n[Outro]\nWe sing as one, we sing as one",
}


class KikuyuPromptEngine:
    """Compile user intent into a provider-neutral music prompt and lyric structure."""

    max_prompt_tokens = 512

    def compose(self, text_prompt, genre, instruments=None, language="gikuyu", mood="joyful", lyrics=""):
        prompt = unicodedata.normalize("NFC", text_prompt).strip()
        if not prompt:
            raise ValueError("A non-empty music prompt is required.")

        genre_slug = getattr(genre, "slug", genre) or self.infer_genre_slug(prompt)
        genre_slug = str(genre_slug or "").lower().replace("_", "-")
        genre_style = GENRE_STYLES.get(genre_slug, "East African contemporary music with authentic Kikuyu musical character")
        instrument_names = [getattr(item, "name", str(item)) for item in (instruments or [])]
        instrument_descriptions = []
        for name in instrument_names:
            normalized = unicodedata.normalize("NFC", name).strip()
            slug = re.sub(r"[^a-z0-9]+", "-", normalized.lower()).strip("-")
            instrument_descriptions.append(INSTRUMENT_PROMPTS.get(slug, INSTRUMENT_PROMPTS.get(normalized.lower(), normalized)))

        sections = [
            f"Create an original song. Style: {genre_style}.",
            f"Mood: {unicodedata.normalize('NFC', mood).strip() or 'joyful'}.",
            f"Creative direction: {prompt}",
            f"Language: {language}; preserve Gĩkũyũ orthography and diacritics (ĩ, ũ, ã, ẽ, õ) exactly.",
        ]
        if instrument_descriptions:
            sections.append("Instrumentation: " + ", ".join(instrument_descriptions) + ".")
        compiled_prompt = " ".join(sections).split()[: self.max_prompt_tokens]
        structured_lyrics = self.structure_lyrics(lyrics, language, prompt, genre_slug)
        return {"compiled_ai_prompt": " ".join(compiled_prompt), "generated_lyrics": structured_lyrics}

    @staticmethod
    def infer_genre_slug(text):
        normalized = unicodedata.normalize("NFC", text).casefold()
        matches = [
            (len(alias), slug)
            for slug, aliases in GENRE_ALIASES.items()
            for alias in aliases
            if alias in normalized
        ]
        return max(matches, default=(0, "mugithi"))[1]

    def structure_lyrics(self, lyrics, language="gikuyu", theme="", genre=""):
        lyrics = unicodedata.normalize("NFC", lyrics or "").strip()
        if lyrics:
            if re.search(r"^\[(Verse|Chorus|Bridge|Interlude|Outro)", lyrics, re.MULTILINE | re.IGNORECASE):
                if genre == "mugithi" and "[Mũgithi Tempo Switch]" not in lyrics:
                    lyrics = lyrics.replace("[Outro]", "[Mũgithi Tempo Switch]\n\n[Outro]", 1)
                return lyrics
            lines = [line.strip() for line in lyrics.splitlines() if line.strip()]
            if not lines:
                return ""
            midpoint = max(1, (len(lines) + 1) // 2)
            verse = "\n".join(lines[:midpoint])
            chorus = "\n".join(lines[midpoint:] or lines[:midpoint])
            tempo_switch = "\n\n[Mũgithi Tempo Switch]" if genre == "mugithi" else ""
            return f"[Verse 1]\n{verse}\n\n[Chorus]\n{chorus}\n\n[Interlude - Guitar Solo]{tempo_switch}\n\n[Outro]\n{chorus}"

        template = LYRIC_TEMPLATES.get(language.lower(), LYRIC_TEMPLATES["gikuyu"])
        safe_theme = unicodedata.normalize("NFC", theme).strip().rstrip(".!?。") or "Wendo witũ"
        lyrics = template.format(theme=safe_theme)
        if genre == "mugithi":
            lyrics = lyrics.replace("[Outro]", "[Mũgithi Tempo Switch]\n\n[Outro]", 1)
        return lyrics.replace("[Interlude - Guitar Solo]", "[Interlude - Guitar Solo]\n")