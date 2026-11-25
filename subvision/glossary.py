"""
SubVision AI — Oyun, Dizi, Film ve Yayın Altyazıları İçin Gelişmiş Metin İşleme Modülü.
OCR gürültü temizleme, SDH/CC ses efekti filtreleme, ALL-CAPS cümle normalizasyonu,
konuşmacı ayrıştırma, günlük konuşma/argo (slang) normalizasyonu ve sıfır gecikmeli (0.003 ms)
sık kullanılan kalıp sözlüğünü içerir.
"""

import re
from typing import Optional, Tuple

# 1. Tam Eşleşme Sözlüğü (0.003 ms'de model çalıştırmadan anında çevrilen popüler dizi, film ve oyun ifadeleri)
EXACT_PHRASES = {
    # Sinema / Dizi & Genel Diyalog Kalıpları
    "previously on": "Önceki bölümlerde",
    "to be continued": "Devam edecek...",
    "to be continued...": "Devam edecek...",
    "the end": "SON",
    "meanwhile": "Bu sırada",
    "one year later": "Bir yıl sonra",
    "six months later": "Altı ay sonra",
    "three days earlier": "Üç gün önce",
    "what happened": "Ne oldu",
    "what happened?": "Ne oldu?",
    "what is going on": "Neler oluyor",
    "what is going on?": "Neler oluyor?",
    "what's going on": "Neler oluyor",
    "what's going on?": "Neler oluyor?",
    "what are you talking about": "Sen neden bahsediyorsun",
    "what are you talking about?": "Sen neden bahsediyorsun?",
    "what do you mean": "Ne demek istiyorsun",
    "what do you mean?": "Ne demek istiyorsun?",
    "are you sure": "Emin misin",
    "are you sure?": "Emin misin?",
    "are you okay": "İyi misin",
    "are you okay?": "İyi misin?",
    "are you all right": "İyi misin",
    "are you all right?": "İyi misin?",
    "you good?": "İyi misin?",
    "i'm fine": "İyiyim",
    "i'm okay": "İyiyim",
    "i'm good": "İyiyim",
    "i'm sorry": "Özür dilerim",
    "i am sorry": "Özür dilerim",
    "so sorry": "Çok özür dilerim",
    "my bad": "Benim hatam",
    "excuse me": "Affedersiniz",
    "excuse me?": "Efendim?",
    "thank you": "Teşekkür ederim",
    "thank you!": "Teşekkür ederim!",
    "thanks": "Teşekkürler",
    "thanks a lot": "Çok teşekkürler",
    "no problem": "Sorun değil",
    "never mind": "Boş ver",
    "forget it": "Unut gitsin",
    "it doesn't matter": "Önemi yok",
    "i don't know": "Bilmiyorum",
    "i have no idea": "Hiçbir fikrim yok",
    "i don't care": "Umurumda değil",
    "i don't understand": "Anlamıyorum",
    "do you understand": "Anlıyor musun",
    "do you understand?": "Anlıyor musun?",
    "we need to talk": "Konuşmamız lazım",
    "listen to me": "Beni dinle",
    "listen to me!": "Beni dinle!",
    "look at me": "Bana bak",
    "look at me!": "Bana bak!",
    "trust me": "Güven bana",
    "believe me": "İnan bana",
    "you have to trust me": "Bana güvenmelisin",
    "don't worry": "Merak etme",
    "be careful": "Dikkatli ol",
    "be careful!": "Dikkatli ol!",
    "take care": "Kendine iyi bak",
    "good luck": "İyi şanslar",
    "good luck!": "İyi şanslar!",
    "of course": "Tabii ki",
    "are you serious": "Ciddi misin",
    "are you serious?": "Ciddi misin?",
    "for real?": "Cidden mi?",
    "you're kidding": "Şaka yapıyorsun",
    "no way": "İmkansız",
    "no way!": "Yok artık!",
    "unbelievable": "İnanılmaz",
    "it's over": "Her şey bitti",
    "it is over": "Her şey bitti",
    "here we go": "İşte başlıyoruz",
    "here we go!": "İşte başlıyoruz!",
    "here we go again": "Yine başlıyoruz",
    "stay with me": "Benimle kal",
    "stay with me!": "Benimle kal!",
    "let me go": "Bırak beni",
    "let me go!": "Bırak beni!",
    "leave me alone": "Beni yalnız bırak",
    "leave me alone!": "Beni rahat bırak!",
    "help me": "Yardım et",
    "help me!": "Yardım edin!",
    "somebody help": "Biri yardım etsin",
    "somebody help!": "Biri yardım etsin!",
    # Oyun & Aksiyon Kalıpları
    "game over": "OYUN BİTTİ",
    "mission passed": "GÖREV TAMAMLANDI",
    "mission failed": "GÖREV BAŞARISIZ",
    "checkpoint reached": "KONTROL NOKTASINA ULAŞILDI",
    "wasted": "ÖLDÜN",
    "busted": "YAKALANDIN",
    "what the fuck": "Ne oluyor lan",
    "what the fuck?": "Ne oluyor lan?",
    "what the fuck!": "Ne oluyor lan!",
    "what the hell": "Ne oluyor be",
    "what the hell?": "Ne oluyor be?",
    "what the hell!": "Ne oluyor be!",
    "son of a bitch": "Kahretsin",
    "son of a bitch!": "Kahretsin!",
    "bullshit": "Saçmalık",
    "bullshit!": "Saçmalık!",
    "holy shit": "Vay canına",
    "holy shit!": "Vay anasını!",
    "oh shit": "Hay aksi",
    "oh shit!": "Kahretsin!",
    "oh my god": "Aman Tanrım",
    "oh my god!": "Aman Tanrım!",
    "shit": "Kahretsin",
    "shit!": "Kahretsin!",
    "fuck": "Kahretsin",
    "fuck!": "Kahretsin!",
    "fuck off": "Defol git",
    "fuck off!": "Defol git!",
    "screw you": "Canın cehenneme",
    "screw you!": "Canın cehenneme!",
    "shut up": "Kes sesini",
    "shut up!": "Kes sesini!",
    "get in the car": "Arabaya bin",
    "get in the car!": "Arabaya bin!",
    "get in": "İçeri gir",
    "get in!": "Atla!",
    "get out": "Dışarı çık",
    "get out!": "Çık dışarı!",
    "get out of here": "Çık git buradan",
    "get out of here!": "Hemen uzaklaş buradan!",
    "get down": "Yere yat",
    "get down!": "Yere yat!",
    "stay down": "Yerde kal",
    "stay down!": "Yerde kal!",
    "back off": "Geri çekil",
    "back off!": "Geri çekil!",
    "chill out": "Sakin ol",
    "calm down": "Sakin ol",
    "calm down!": "Sakin ol!",
    "cover me": "Beni koru",
    "cover me!": "Beni koru!",
    "reloading": "Şarjör değiştiriyorum",
    "reloading!": "Şarjör değiştiriyorum!",
    "man down": "Yaralı var",
    "man down!": "Adam vuruldu!",
    "watch out": "Dikkat et",
    "watch out!": "Dikkat et!",
    "look out": "Dikkat et",
    "look out!": "Dikkat et!",
    "hold on": "Bekle biraz",
    "hold on!": "Sıkı tutun!",
    "wait up": "Bekle beni",
    "wait a minute": "Bir dakika bekle",
    "wait a second": "Bir saniye bekle",
    "let's go": "Hadi gidelim",
    "let's go!": "Hadi gidelim!",
    "let's move": "Hadi hareketlen",
    "come on": "Hadi ama",
    "come on!": "Hadi!",
    "hands up": "Eller yukarı",
    "hands up!": "Eller yukarı!",
    "put your hands up": "Ellerini kaldır",
    "put your hands up!": "Ellerini kaldır!",
    "freeze": "Olduğun yerde kal",
    "freeze!": "Kıpırdama!",
    "drop the weapon": "Silahı bırak",
    "drop the weapon!": "Silahı bırak!",
    "drop your weapon": "Silahını bırak",
    "drop your weapon!": "Silahını bırak!",
    "don't move": "Kıpırdama",
    "don't move!": "Kıpırdama!",
    "don't shoot": "Ateş etme",
    "don't shoot!": "Ateş etme!",
    "are you crazy?": "Delirdin mi sen?",
    "are you out of your mind?": "Aklını mı kaçırdın?",
    "hell yeah": "İşte bu be",
    "hell yeah!": "İşte bu be!",
    "damn it": "Lanet olsun",
    "damn it!": "Lanet olsun!",
    "dammit": "Lanet olsun",
    "dammit!": "Lanet olsun!",
    "goddamn it": "Kahretsin",
    "goddamn it!": "Kahretsin!",
    "follow me": "Beni takip et",
    "stay close": "Yakınımda kal",
    "hurry up": "Acele et",
    "hurry up!": "Acele et!",
    "move it": "Kıpırda",
    "move it!": "Hızlı ol!",
    "over there": "Şurada",
    "over there!": "Şurada!",
}

# 2. Günlük Konuşma Dili & Kısaltmalar (Colloquial / Slang) -> NMT Modelinin En Doğru Çevirdiği Forma Dönüştürme
SLANG_PATTERNS = [
    (re.compile(r"\bgonna\b", re.IGNORECASE), "going to"),
    (re.compile(r"\bwanna\b", re.IGNORECASE), "want to"),
    (re.compile(r"\bgotta\b", re.IGNORECASE), "have got to"),
    (re.compile(r"\blemme\b", re.IGNORECASE), "let me"),
    (re.compile(r"\bgimme\b", re.IGNORECASE), "give me"),
    (re.compile(r"\bdunno\b", re.IGNORECASE), "do not know"),
    (re.compile(r"\bkinda\b", re.IGNORECASE), "kind of"),
    (re.compile(r"\bsorta\b", re.IGNORECASE), "sort of"),
    (re.compile(r"\boutta\b", re.IGNORECASE), "out of"),
    (re.compile(r"\blotta\b", re.IGNORECASE), "lot of"),
    (re.compile(r"\bc'mon\b", re.IGNORECASE), "come on"),
    (re.compile(r"\bcmon\b", re.IGNORECASE), "come on"),
    (re.compile(r"\by'all\b", re.IGNORECASE), "you all"),
    (re.compile(r"\byall\b", re.IGNORECASE), "you all"),
    (re.compile(r"\btryna\b", re.IGNORECASE), "trying to"),
    (re.compile(r"\bfinna\b", re.IGNORECASE), "going to"),
    (re.compile(r"\bwhatcha\b", re.IGNORECASE), "what are you"),
    (re.compile(r"\bgotcha\b", re.IGNORECASE), "got you"),
    (re.compile(r"\bain't\b", re.IGNORECASE), "is not"),
    (re.compile(r"\baint\b", re.IGNORECASE), "is not"),
    (re.compile(r"(?<!\w)'cause\b", re.IGNORECASE), "because"),
    (re.compile(r"\bcuz\b", re.IGNORECASE), "because"),
    (re.compile(r"(?<!\w)'em\b", re.IGNORECASE), "them"),
    (re.compile(r"\bhomie\b", re.IGNORECASE), "my friend"),
    (re.compile(r"\bhomies\b", re.IGNORECASE), "my friends"),
    (re.compile(r"\bdawg\b", re.IGNORECASE), "buddy"),
    (re.compile(r"\bbro\b", re.IGNORECASE), "brother"),
    (re.compile(r"\bcops\b", re.IGNORECASE), "police"),
    (re.compile(r"\bfive-o\b", re.IGNORECASE), "police"),
    (re.compile(r"\bfeds\b", re.IGNORECASE), "federal agents"),
    (re.compile(r"\bsnitch\b", re.IGNORECASE), "informant"),
    (re.compile(r"\bstash\b", re.IGNORECASE), "hidden supply"),
    (re.compile(r"\bheist\b", re.IGNORECASE), "robbery"),
    (re.compile(r"\bgetaway\b", re.IGNORECASE), "escape"),
    (re.compile(r"\bnah\b", re.IGNORECASE), "no"),
    (re.compile(r"\byeah\b", re.IGNORECASE), "yes"),
    (re.compile(r"\byep\b", re.IGNORECASE), "yes"),
    (re.compile(r"\bnope\b", re.IGNORECASE), "no"),
    (re.compile(r"\bdammit\b", re.IGNORECASE), "damn it"),
]

# OCR hatalarını ve Dizi/Film SDH (İşitme Engelli Ses Betimlemeleri) etiketlerini temizlemek için Regex kuralları
RE_MULTISPACE = re.compile(r"\s+")
RE_OCR_NOISE = re.compile(r"[^a-zA-Z0-9\s.,!?'\":;\-\(\)\[\]]")
# Çok dilli (Aksanlı Latin, Kiril, Japonca/CJK) altyazılar için güvenli Unicode temizleme
RE_OCR_NOISE_UNICODE = re.compile(
    r"[^\w\s.,!?'\":;\-\(\)\[\]¡¿«»„‚…—–。、「」『』！？・〜ー（）【】《》：；]",
    re.UNICODE,
)

# Netflix / Prime Video / Blu-ray SDH ses efekti parantezleri: [sighs], (dramatic music), [laughs], (gunshot) vb.
RE_SDH_SOUND_TAGS = re.compile(
    r"[\[\(][^\]\)]*(?:music|sigh|laugh|groan|grunt|gasp|pant|cough|chuckle|sob|cry|scream|shout|whisper|applause|cheer|thunder|explosion|gunshot|siren|ringing|knock|slam|footstep|wind|rain|audio|sound|speaking|indistinct)[^\]\)]*[\]\)]",
    re.IGNORECASE,
)

# Konuşmacı ismi yakalama: örn. "Detective: Wait here!" veya "[Arthur] Once upon a time..."
RE_SPEAKER_COLON = re.compile(r"^([A-Z][a-zA-Z0-9\s]{1,20}):\s+(.+)$")
# Köşeli parantezde konuşmacı: yalnızca Baş Harfi Büyük özel isim (örn. [Arthur] veya [Narrator])
RE_SPEAKER_BRACKET = re.compile(r"^\[([A-Z][a-zA-Z0-9]{1,18})\]\s*(.+)$")

# Yaygın OCR harf karışıklıkları (örn. "l'm" -> "I'm", "0" -> "O" harf içinde)
RE_OCR_L_TO_I = re.compile(r"\bl'([mMdDsS]|ll|ve|re)\b")
RE_OCR_STANDALONE_L = re.compile(r"\bl\b")
RE_ZERO_IN_WORD = re.compile(r"(?<=[A-Za-z])0(?=[A-Za-z])|(?<=[A-Z])0\b|\b0(?=[A-Za-z])")
RE_STANDALONE_I_CONTRACT = re.compile(r"\bi('m|'ve|'ll|'d)?\b")


def _normalize_source_lang(source_lang: Optional[str]) -> str:
    raw = (source_lang or "en").strip().lower()
    if not raw:
        return "en"
    return raw.split("-")[0].split("_")[0] or "en"


def _has_cjk_or_kana(text: str) -> bool:
    for ch in text:
        code = ord(ch)
        if (
            0x3040 <= code <= 0x30FF  # Hiragana & Katakana
            or 0x3400 <= code <= 0x4DBF  # CJK Unified Ideographs Extension A
            or 0x4E00 <= code <= 0x9FFF  # CJK Unified Ideographs
            or 0xAC00 <= code <= 0xD7AF  # Hangul Syllables
            or 0xF900 <= code <= 0xFAFF  # CJK Compatibility Ideographs
        ):
            return True
    return False


def normalize_all_caps_text(text: str, source_lang: str = "en") -> str:
    """
    Bazı oyun ve filmler altyazıları tamamen BÜYÜK HARFLE (ALL CAPS) yazar.
    SentencePiece tokenizer tamamen büyük harfli kelimeleri alt-hecelere böldüğü için
    çeviri kalitesini düşürür (örn. 'CONSPIRACY' -> 'dengeye', 'conspiracy' -> 'komploya').
    Bu fonksiyon ALL-CAPS metinleri doğal cümle düzenine (Sentence Case) dönüştürür.
    """
    letters = [c for c in text if c.isalpha()]
    if len(letters) < 5:
        return text
    upper_ratio = sum(1 for c in letters if c.isupper()) / len(letters)
    if upper_ratio < 0.75:
        return text

    lowered = text.lower()
    # Cümle başlarını büyük harfe çevir
    sentences = re.split(r"([.!?]\s+)", lowered)
    rebuilt = []
    for part in sentences:
        if part and part[0].isalpha():
            rebuilt.append(part[0].upper() + part[1:])
        else:
            rebuilt.append(part)
    res = "".join(rebuilt)
    if res and res[0].isalpha():
        res = res[0].upper() + res[1:]

    # İngilizce 'I', 'I'm', 'I'll', 'I've', 'I'd' zamirlerini büyük 'I' yap
    if _normalize_source_lang(source_lang) == "en":
        res = RE_STANDALONE_I_CONTRACT.sub(lambda m: "I" + (m.group(1) or ""), res)
    return res


def clean_ocr_text(raw_text: str, source_lang: str = "en") -> str:
    """
    OCR'dan gelen ham altyazıyı kaynak dile (`source_lang`) uygun biçimde temizler,
    SDH ses efektlerini çıkarır ve İngilizce OCR harf/rakam karışıklıklarını düzeltir.
    Aksanlı Latin (ES/DE/FR/PT/IT), Kiril (RU) ve Japonca/CJK (JA) karakterlerini korur.
    """
    if not raw_text:
        return ""

    lang = _normalize_source_lang(source_lang)
    text = raw_text.replace("\n", " ").replace("\r", " ")
    text = text.replace("—", "-").replace("–", "-")
    text = text.replace("“", '"').replace("”", '"').replace("’", "'").replace("‘", "'")

    if lang == "en":
        text = text.replace("|", "I")
        # İzin verilen İngilizce karakterler dışındaki parazitleri sil
        text = RE_OCR_NOISE.sub("", text)
        # Dizi/Filmlerdeki [dramatic music], [sighs], (laughs) gibi işitme engelli ses etiketlerini temizle
        text = RE_SDH_SOUND_TAGS.sub(" ", text)
        # Kelime içindeki '0' (sıfır) rakamını 'O' harfine düzelt (örn. "H0LD 0N" -> "HOLD ON")
        text = RE_ZERO_IN_WORD.sub("O", text)
        # OCR'ın 'I' harfini küçük 'l' olarak okuma hatasını düzelt ("l'm" -> "I'm", " l " -> " I ")
        text = RE_OCR_L_TO_I.sub(r"I'\1", text)
        text = RE_OCR_STANDALONE_L.sub("I", text)
    else:
        text = RE_SDH_SOUND_TAGS.sub(" ", text)
        text = RE_OCR_NOISE_UNICODE.sub("", text)

    # Fazla boşlukları teke indir
    text = RE_MULTISPACE.sub(" ", text).strip()
    text = text.strip("-_~.:;")

    # Çok kısa parazitleri (tek harf, sadece rakam/noktalama vb.) yoksay
    alpha_count = sum(1 for c in text if c.isalpha())
    if lang in ("ja", "zh", "ko") or _has_cjk_or_kana(text):
        if len(text) < 1 or alpha_count < 1:
            return ""
    elif len(text) < 2 or alpha_count < 2:
        return ""

    return text


def extract_speaker_and_body(text: str, source_lang: str = "en") -> Tuple[Optional[str], str]:
    """
    Altyazıda konuşmacı adı varsa ('Arthur: Hold on!' veya '[Narrator] Wait!') ayırır
    ve gövde metninde ALL-CAPS normalizasyonu uygular.
    """
    m1 = RE_SPEAKER_COLON.match(text)
    if m1:
        speaker = m1.group(1).strip()
        if speaker.isupper() and len(speaker) > 2:
            speaker = speaker.title()
        return speaker, normalize_all_caps_text(m1.group(2).strip(), source_lang=source_lang)

    m2 = RE_SPEAKER_BRACKET.match(text)
    if m2:
        speaker = m2.group(1).strip()
        if speaker.isupper() and len(speaker) > 2:
            speaker = speaker.title()
        return speaker, normalize_all_caps_text(m2.group(2).strip(), source_lang=source_lang)

    return None, normalize_all_caps_text(text, source_lang=source_lang)


def lookup_exact_phrase(text: str) -> Optional[str]:
    """
    Sık kullanılan kalıp ifadeleri 0.003 ms'de sözlükten döndürür.
    """
    stripped = text.strip()
    if not stripped:
        return None
    key = stripped.lower()
    if key in EXACT_PHRASES:
        return EXACT_PHRASES[key]
    key_no_punct = key.rstrip(".!?")
    if key_no_punct in EXACT_PHRASES:
        suffix = stripped[-1] if stripped[-1] in ".!?" else ""
        res = EXACT_PHRASES[key_no_punct].rstrip(".!?")
        return res + suffix
    return None


def normalize_slang_for_nmt(text: str) -> str:
    """
    İngilizce konuşma dili kısaltmalarını ve argoyu NMT modelinin en iyi çevirdiği forma dönüştürür.
    """
    result = text
    for pattern, replacement in SLANG_PATTERNS:
        result = pattern.sub(replacement, result)
    return result


# Oyun/film arka plan dokularından kaynaklanan hayalet OCR parazitlerini elemek için
# geçerli kısa İngilizce ifadeler ve sesli harf/tekrar kuralları
SHORT_VALID_WORDS = frozenset(
    {
        "no", "ok", "hi", "me", "go", "up", "oh", "ah", "ya", "so", "do", "be",
        "he", "we", "us", "it", "in", "on", "to", "my", "if", "or", "by", "mj",
        "yes", "hey", "run", "who", "why", "how", "now", "out", "off", "all",
        "get", "let", "god", "man", "sir", "kid", "mom", "dad", "bro", "doc",
        "car", "gun", "cop", "way", "day", "one", "two", "end", "die", "hit",
        "bye", "huh", "ugh", "wow", "hmm", "shh", "cry", "try", "fly", "spy",
        "sky", "dry", "wtf", "omg", "you", "she", "him", "her", "not", "too",
        "see", "did", "can", "are", "was", "has", "had", "big", "bad", "new",
        "old", "own", "our", "out", "put", "say", "use", "may", "boy", "war",
        "eye", "far", "few", "got", "hot", "job", "law", "lot", "low", "pay",
        "red", "set", "sit", "six", "ten", "top", "win", "yet", "yep", "nah",
    }
)
_VOWELS = frozenset("aeiouyAEIOUY")
_UNICODE_VOWELS = frozenset(
    "aeiouyAEIOUY"
    "áéíóúàèìòùâêîôûäëïöüãõåæœøýÿıİ"
    "ÁÉÍÓÚÀÈÌÒÙÂÊÎÔÛÄËÏÖÜÃÕÅÆŒØÝŸ"
    "аеёиоуыэюяАЕЁИОУЫЭЮЯ"
)
_RE_REPEATED_RUN = re.compile(r"(.)\1{3,}")
_RE_REPEATED_RUN_CJK = re.compile(r"(.)\1{5,}")
_RE_ALPHA_WORDS = re.compile(r"[A-Za-z]+(?:'[A-Za-z]+)?")
_RE_UNICODE_WORDS = re.compile(r"[^\W\d_]+(?:'[^\W\d_]+)?", re.UNICODE)


def is_plausible_subtitle_text(
    text: str,
    avg_confidence: float = 1.0,
    source_lang: str = "en",
) -> bool:
    """
    OCR'dan gelen temizlenmiş metnin gerçek bir altyazı olup olmadığını doğrular.
    Oyun arka planı, far, pencere kenarı veya HUD parazitlerinden doğan anlamsız harf
    yığınlarını sıfır maliyetle elerken çok dilli (ES/DE/FR/PT/IT/RU/JA) altyazıları korur.
    """
    if not text:
        return False

    stripped = text.strip()
    lang = _normalize_source_lang(source_lang)
    is_cjk = lang in ("ja", "zh", "ko") or _has_cjk_or_kana(stripped)

    if is_cjk:
        if len(stripped) < 1:
            return False
        if _RE_REPEATED_RUN_CJK.search(stripped):
            return False
        non_space = [c for c in stripped if not c.isspace()]
        if not non_space:
            return False
        alpha_chars = [c for c in non_space if c.isalpha()]
        if len(alpha_chars) < 1:
            return False
        if (len(alpha_chars) / len(non_space)) < 0.35:
            return False
        return avg_confidence >= 0.50

    if len(stripped) < 2:
        return False

    # Aşırı tekrarlı tek karakter parazitlerini reddet (örn. "IIII", "llll", "oooo")
    if _RE_REPEATED_RUN.search(stripped):
        return False

    # Harf oranı çok düşükse (sembol/rakam çöpü) reddet
    non_space = [c for c in stripped if not c.isspace()]
    if not non_space:
        return False
    alpha_chars = [c for c in non_space if c.isalpha()]
    if len(alpha_chars) < 2:
        return False
    if (len(alpha_chars) / len(non_space)) < 0.45:
        return False

    if lang != "en":
        words = _RE_UNICODE_WORDS.findall(stripped)
        if not words:
            return False
        if len(words) == 1:
            wl = words[0].lower()
            if not any(ch in _UNICODE_VOWELS for ch in wl):
                return False
            return avg_confidence >= (0.65 if len(wl) <= 3 else 0.62)

        plausible_words = 0
        for w in words:
            wl = w.lower()
            if len(wl) == 1:
                plausible_words += 1
            elif any(ch in _UNICODE_VOWELS for ch in wl):
                plausible_words += 1

        if (plausible_words / len(words)) < 0.50:
            return False
        return avg_confidence >= 0.55

    words = _RE_ALPHA_WORDS.findall(stripped)
    if not words:
        return False

    # Tek kelimelik çok kısa çıktılarda (2-3 harf) sözlük veya çok yüksek güven şartı ara
    if len(words) == 1:
        w = words[0]
        wl = w.lower()
        if len(wl) <= 3:
            if wl in SHORT_VALID_WORDS:
                return avg_confidence >= 0.68
            return False
        # 4+ harfli tek kelimede en az 1 sesli harf (a,e,i,o,u,y) bulunmalı
        if not any(ch in _VOWELS for ch in wl):
            return False
        return avg_confidence >= 0.68

    # Çok kelimelik cümlelerde gerçek okunabilir kelime oranını kontrol et
    plausible_words = 0
    for w in words:
        wl = w.lower()
        if len(wl) == 1 and wl in ("i", "a"):
            plausible_words += 1
        elif wl in SHORT_VALID_WORDS:
            plausible_words += 1
        elif len(wl) >= 2 and any(ch in _VOWELS for ch in wl):
            plausible_words += 1

    if (plausible_words / len(words)) < 0.50:
        return False

    return avg_confidence >= 0.58
