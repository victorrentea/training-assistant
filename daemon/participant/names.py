"""Avatar and name assignment logic for participant identity."""
import random

LOTR_NAMES = [
    # Ordered by cultural popularity: most recognizable → least
    "Gandalf", "Frodo", "Aragorn", "Legolas", "Gollum",
    "Samwise", "Gimli", "Smaug", "Bilbo", "Saruman",
    "Galadriel", "Boromir", "Arwen", "Eowyn", "Merry",
    "Pippin", "Elrond", "Thorin", "Theoden", "Faramir",
    "Treebeard", "Shadowfax", "Radagast", "Tom Bombadil", "Eomer",
    "Haldir", "Glorfindel", "Celeborn", "Grima Wormtongue", "The One Ring"
]

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


def get_avatar_filename(name: str) -> str:
    return name.lower().replace(' ', '-') + '.png'


def assign_avatar(state, uuid: str, name: str) -> str:
    """Assign avatar based on name. LOTR names get their matching avatar on first
    assignment. Custom names get a unique avatar based on name hash.
    Never overwrites an existing avatar (preserves refresh_avatar choices)."""
    if uuid in state.participant_avatars:
        return state.participant_avatars[uuid]
    if name in LOTR_NAMES:
        avatar = get_avatar_filename(name)
        state.participant_avatars[uuid] = avatar
        return avatar
    taken = set(state.participant_avatars.values())
    name_hash = sum(ord(c) for c in name) * 2654435761
    preferred_index = name_hash % len(LOTR_NAMES)
    for offset in range(len(LOTR_NAMES)):
        avatar = get_avatar_filename(LOTR_NAMES[(preferred_index + offset) % len(LOTR_NAMES)])
        if avatar not in taken:
            state.participant_avatars[uuid] = avatar
            return avatar
    avatar = get_avatar_filename(LOTR_NAMES[preferred_index])
    state.participant_avatars[uuid] = avatar
    return avatar


def refresh_avatar(state, uuid: str, rejected: set[str] | None = None) -> str | None:
    """Reassign a random avatar different from current and any previously rejected,
    ensuring uniqueness among connected participants."""
    current = state.participant_avatars.get(uuid)
    rejected = rejected or set()
    if current:
        rejected.add(current)

    taken_by_others = {avatar for uid, avatar in state.participant_avatars.items()
                       if uid != uuid and not uid.startswith("__")}
    all_avatars = [get_avatar_filename(n) for n in LOTR_NAMES]

    available = [a for a in all_avatars if a not in taken_by_others and a not in rejected]
    if not available:
        available = [a for a in all_avatars if a not in taken_by_others and a != current]
    if not available:
        available = [a for a in all_avatars if a != current]
    if not available:
        return None
    new_avatar = random.choice(available)
    state.participant_avatars[uuid] = new_avatar
    return new_avatar


def assign_conference_name(state) -> tuple[str, str]:
    """Pick a random unused character name for a new conference participant.
    Returns (name, universe). Unused = not assigned to any currently connected UUID.
    """
    connected_uuids = {uid for uid in state.participants if not uid.startswith("__")}
    used_names = {state.participant_names.get(uid) for uid in connected_uuids
                  if uid in state.participant_names}
    available = [(n, u) for n, u in CHARACTER_NAMES if n not in used_names]
    if available:
        return random.choice(available)
    short_id = hex(random.randint(0, 0xFFFF))[2:].upper()
    return (f"Hero-{short_id}", "")
