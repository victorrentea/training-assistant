"""Character name pool for conference mode auto-assignment."""
import hashlib

CHARACTER_NAMES: list[tuple[str, str]] = [
    # Star Wars
    ("Yoda", "Star Wars"), ("Luke", "Star Wars"), ("Leia", "Star Wars"),
    ("Han Solo", "Star Wars"), ("Chewbacca", "Star Wars"), ("Obi-Wan", "Star Wars"),
    ("Darth Vader", "Star Wars"), ("Palpatine", "Star Wars"), ("Mace Windu", "Star Wars"),
    ("Ahsoka", "Star Wars"), ("Boba Fett", "Star Wars"), ("Jango Fett", "Star Wars"),
    ("Padme", "Star Wars"), ("Anakin", "Star Wars"), ("Rey", "Star Wars"),
    ("Kylo Ren", "Star Wars"), ("Finn", "Star Wars"), ("Poe", "Star Wars"),
    ("Lando", "Star Wars"), ("Jabba", "Star Wars"), ("Grievous", "Star Wars"),
    ("Dooku", "Star Wars"), ("Maul", "Star Wars"), ("Qui-Gon", "Star Wars"),
    ("R2-D2", "Star Wars"), ("C-3PO", "Star Wars"), ("BB-8", "Star Wars"),
    ("Grogu", "Star Wars"), ("Mandalorian", "Star Wars"), ("Tarkin", "Star Wars"),
    # LOTR
    ("Gandalf", "LOTR"), ("Frodo", "LOTR"), ("Aragorn", "LOTR"),
    ("Legolas", "LOTR"), ("Gimli", "LOTR"), ("Samwise", "LOTR"),
    ("Boromir", "LOTR"), ("Faramir", "LOTR"), ("Gollum", "LOTR"),
    ("Saruman", "LOTR"), ("Elrond", "LOTR"), ("Galadriel", "LOTR"),
    ("Theoden", "LOTR"), ("Eowyn", "LOTR"), ("Eomer", "LOTR"),
    ("Treebeard", "LOTR"), ("Sauron", "LOTR"), ("Pippin", "LOTR"),
    ("Merry", "LOTR"), ("Arwen", "LOTR"), ("Bilbo", "LOTR"),
    ("Radagast", "LOTR"), ("Haldir", "LOTR"), ("Denethor", "LOTR"),
    # Matrix
    ("Neo", "Matrix"), ("Morpheus", "Matrix"), ("Trinity", "Matrix"),
    ("Agent Smith", "Matrix"), ("Oracle", "Matrix"), ("Niobe", "Matrix"),
    ("Cypher", "Matrix"), ("Tank", "Matrix"), ("Apoc", "Matrix"),
    ("Mouse", "Matrix"), ("Dozer", "Matrix"), ("Merovingian", "Matrix"),
    ("Seraph", "Matrix"), ("Architect", "Matrix"), ("Keymaker", "Matrix"),
    # Marvel
    ("Iron Man", "Marvel"), ("Thor", "Marvel"), ("Hulk", "Marvel"),
    ("Black Widow", "Marvel"), ("Hawkeye", "Marvel"), ("Spider-Man", "Marvel"),
    ("Black Panther", "Marvel"), ("Doctor Strange", "Marvel"), ("Scarlet Witch", "Marvel"),
    ("Vision", "Marvel"), ("Ant-Man", "Marvel"), ("Wasp", "Marvel"),
    ("Captain Marvel", "Marvel"), ("Falcon", "Marvel"), ("Groot", "Marvel"),
    ("Rocket", "Marvel"), ("Gamora", "Marvel"), ("Drax", "Marvel"),
    ("Star-Lord", "Marvel"), ("Nebula", "Marvel"), ("Thanos", "Marvel"),
    ("Loki", "Marvel"), ("Shang-Chi", "Marvel"), ("Moon Knight", "Marvel"),
    ("Wolverine", "Marvel"), ("Deadpool", "Marvel"), ("Storm", "Marvel"),
    ("Magneto", "Marvel"), ("Professor X", "Marvel"), ("Cyclops", "Marvel"),
    # Star Trek
    ("Kirk", "Star Trek"), ("Spock", "Star Trek"), ("McCoy", "Star Trek"),
    ("Scotty", "Star Trek"), ("Uhura", "Star Trek"), ("Sulu", "Star Trek"),
    ("Chekov", "Star Trek"), ("Picard", "Star Trek"), ("Riker", "Star Trek"),
    ("Data", "Star Trek"), ("Worf", "Star Trek"), ("Troi", "Star Trek"),
    ("Crusher", "Star Trek"), ("LaForge", "Star Trek"), ("Janeway", "Star Trek"),
    ("Seven of Nine", "Star Trek"), ("Tuvok", "Star Trek"), ("Sisko", "Star Trek"),
    ("Odo", "Star Trek"), ("Quark", "Star Trek"),
    # Harry Potter
    ("Harry Potter", "HP"), ("Hermione", "HP"), ("Ron Weasley", "HP"),
    ("Dumbledore", "HP"), ("Snape", "HP"), ("Voldemort", "HP"),
    ("Hagrid", "HP"), ("McGonagall", "HP"), ("Sirius Black", "HP"),
    ("Lupin", "HP"), ("Draco Malfoy", "HP"), ("Dobby", "HP"),
    ("Luna", "HP"), ("Neville", "HP"), ("Bellatrix", "HP"),
    ("Moody", "HP"), ("Tonks", "HP"), ("Cedric", "HP"),
    ("Fred Weasley", "HP"), ("George Weasley", "HP"),
    # Dune
    ("Paul Atreides", "Dune"), ("Chani", "Dune"), ("Duncan Idaho", "Dune"),
    ("Stilgar", "Dune"), ("Lady Jessica", "Dune"), ("Baron Harkonnen", "Dune"),
    ("Feyd-Rautha", "Dune"), ("Leto Atreides", "Dune"), ("Gurney Halleck", "Dune"),
    ("Thufir Hawat", "Dune"), ("Alia", "Dune"), ("Irulan", "Dune"),
    # Back to the Future
    ("Doc Brown", "BTTF"), ("Marty McFly", "BTTF"), ("Biff Tannen", "BTTF"),
    ("Jennifer Parker", "BTTF"), ("Lorraine", "BTTF"), ("George McFly", "BTTF"),
    # Blade Runner
    ("Deckard", "Blade Runner"), ("Roy Batty", "Blade Runner"), ("Rachael", "Blade Runner"),
    ("Pris", "Blade Runner"), ("K", "Blade Runner"), ("Joi", "Blade Runner"),
    ("Gaff", "Blade Runner"), ("Tyrell", "Blade Runner"),
    # Hitchhiker's Guide
    ("Arthur Dent", "H2G2"), ("Ford Prefect", "H2G2"), ("Zaphod", "H2G2"),
    ("Trillian", "H2G2"), ("Marvin", "H2G2"), ("Deep Thought", "H2G2"),
    ("Slartibartfast", "H2G2"),
    # Alien/Aliens
    ("Ripley", "Alien"), ("Bishop", "Alien"), ("Newt", "Alien"),
    ("Hicks", "Alien"), ("Dallas", "Alien"), ("Ash", "Alien"),
    # Terminator
    ("T-800", "Terminator"), ("Sarah Connor", "Terminator"), ("John Connor", "Terminator"),
    ("T-1000", "Terminator"), ("Kyle Reese", "Terminator"),
    # The Expanse
    ("Holden", "Expanse"), ("Naomi", "Expanse"), ("Amos", "Expanse"),
    ("Alex", "Expanse"), ("Bobbie", "Expanse"), ("Avasarala", "Expanse"),
    ("Miller", "Expanse"), ("Drummer", "Expanse"),
    # Firefly
    ("Mal Reynolds", "Firefly"), ("Zoe", "Firefly"), ("Wash", "Firefly"),
    ("Inara", "Firefly"), ("Kaylee", "Firefly"), ("Jayne", "Firefly"),
    ("River Tam", "Firefly"), ("Simon Tam", "Firefly"), ("Shepherd", "Firefly"),
    # Tron
    ("Flynn", "Tron"), ("Tron", "Tron"), ("Quorra", "Tron"),
    ("Rinzler", "Tron"), ("CLU", "Tron"),
    # DC
    ("Batman", "DC"), ("Superman", "DC"), ("Wonder Woman", "DC"),
    ("Flash", "DC"), ("Aquaman", "DC"), ("Green Lantern", "DC"),
    ("Joker", "DC"), ("Catwoman", "DC"), ("Harley Quinn", "DC"),
    ("Alfred", "DC"), ("Robin", "DC"), ("Cyborg", "DC"),
    # Video Games
    ("Mario", "Nintendo"), ("Link", "Zelda"), ("Samus", "Metroid"),
    ("Master Chief", "Halo"), ("Kratos", "God of War"), ("Geralt", "Witcher"),
    ("Commander Shepard", "Mass Effect"), ("Gordon Freeman", "Half-Life"),
    ("GLaDOS", "Portal"), ("Chell", "Portal"),
    ("Solid Snake", "Metal Gear"), ("Lara Croft", "Tomb Raider"),
    ("Ezio", "Assassin's Creed"), ("Joel", "Last of Us"), ("Ellie", "Last of Us"),
    ("Cloud", "FF7"), ("Tifa", "FF7"), ("Sephiroth", "FF7"),
    ("Aloy", "Horizon"), ("Kirby", "Nintendo"),
    # Misc Sci-Fi
    ("HAL 9000", "2001"), ("Dave Bowman", "2001"),
    ("Optimus Prime", "Transformers"), ("Megatron", "Transformers"),
    ("Wall-E", "Pixar"), ("EVE", "Pixar"),
    ("Godzilla", "Kaiju"), ("Mothra", "Kaiju"),
    ("Robocop", "Robocop"), ("Judge Dredd", "2000 AD"),
    ("The Doctor", "Doctor Who"), ("Dalek", "Doctor Who"),
    ("Sherlock", "BBC"), ("John Watson", "BBC"),
]


def compute_letter_avatar(name: str) -> tuple[str, str]:
    """Return (2-letter code, hex color) for a name.
    Letters = first 2 chars of name uppercased.
    Color = deterministic hash-based HSL color.
    """
    letters = name.replace("-", "").replace(" ", "")[:2].upper()
    if len(letters) < 2:
        letters = letters.ljust(2, "X")
    h = int(hashlib.md5(name.encode()).hexdigest()[:8], 16)
    hue = h % 360
    sat = 55 + (h >> 8) % 25   # 55-80%
    lum = 45 + (h >> 16) % 15  # 45-60%
    color = f"hsl({hue},{sat}%,{lum}%)"
    return letters, color


def assign_conference_name(state) -> tuple[str, str]:
    """Pick a random unused character name for a new conference participant.
    Returns (name, universe). Unused = not assigned to any currently connected UUID.
    """
    import random
    connected_uuids = {uid for uid in state.participants if not uid.startswith("__")}
    used_names = {state.participant_names.get(uid) for uid in connected_uuids
                  if uid in state.participant_names}
    available = [(n, u) for n, u in CHARACTER_NAMES if n not in used_names]
    if available:
        return random.choice(available)
    short_id = hex(random.randint(0, 0xFFFF))[2:].upper()
    return (f"Hero-{short_id}", "")
