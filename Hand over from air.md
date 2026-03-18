### Hand over from Air - Implementare FAISS & RAG (Retrieval-Augmented Generation)

Acest document sumarizează funcționalitățile noi implementate pentru asistentul de training, axate pe indexarea materialelor tehnice și îmbunătățirea generării de quiz-uri folosind context local.

---

### 1. Funcționalități Implementate

#### **Indexare Materiale (FAISS)**
- **Script:** `index_materials.py`
- **Descriere:** Permite încărcarea automată a documentelor (`.pdf`, `.txt`, `.md`) din directorul `materials/`.
- **Tehnologie:** Folosește `LangChain` pentru procesare, `RecursiveCharacterTextSplitter` pentru fragmentarea textului (chunks) și `FAISS` (Facebook AI Similarity Search) pentru baza de date vectorială locală.
- **Embeddings:** Utilizează modelul local `sentence-transformers/all-MiniLM-L6-v2` (rulează rapid pe CPU, cost zero, nu trimite date extern pentru embeddings).

#### **Căutare Semantică (RAG)**
- **Funcție:** `search_materials(query)` în `quiz_core.py`.
- **Descriere:** Permite interogarea indexului FAISS pentru a găsi cele mai relevante fragmente de text bazate pe o interogare în limbaj natural.
- **Integrare Claude:** Claude are acum acces la un tool numit `search_materials`. Când detectează concepte complexe (ex: "Outbox", "Circuit Breaker") sau când primește un topic specific, Claude apelează automat acest tool pentru a-și fundamenta întrebările pe materialele furnizate.

#### **Generare Quiz pe bază de Topic**
- **CLI:** `quiz_generator.py --topic "Nume Topic"`
- **Descriere:** S-a adăugat suport pentru generarea de întrebări pornind direct de la un concept/topic, fără a fi necesară o transcriere curentă. Sistemul va căuta detalii în indexul FAISS pentru acel topic.

---

### 2. Mod de Folosire

#### **Pasul 1: Pregătirea documentelor**
Adaugă fișierele tale PDF, TXT sau MD în folderul `materials/`.

#### **Pasul 2: Generarea/Actualizarea Indexului**
Rulează comanda următoare de fiecare dată când adaugi materiale noi:
```bash
uv run python3 index_materials.py
```
Indexul va fi salvat local în folderul `faiss_index/`.

#### **Pasul 3: Testarea căutării (Opțional)**
Poți verifica dacă indexul funcționează corect folosind scriptul de test:
```bash
uv run python3 test_search.py "Transactional Outbox"
```

#### **Pasul 4: Generarea de Quiz-uri**
- **Din transcriere (automat):** Rulează `quiz_daemon.py`. Claude va folosi indexul automat dacă detectează termeni tehnici relevanți în discuție.
- **Pe un topic specific:**
  ```bash
  uv run python3 quiz_generator.py --topic "Circuit Breaker"
  ```

---

### 3. Note Tehnice
- Toate comentariile și mesajele din cod au fost traduse în **limba engleză**, conform standardelor proiectului.
- S-a folosit `uv` pentru managementul dependențelor și execuție.
- Pentru medii fără acces la internet, prima rulare necesită descărcarea modelului de embeddings de pe HuggingFace.
