# Store knowledge retrieval (RAG)

The agent can call `search_store_knowledge` before answering care, material, sizing-guidance and policy questions. The backend retrieves up to three seller-owned passages from PostgreSQL, gives them to the existing OpenRouter model, and appends an application-generated **Sources consulted** footer. The footer is persisted in chat history and works in the existing live frontend without a UI change. It identifies retrieved documents; it is not a proof that every generated claim is supported.

## Cost and scope

- No paid embedding API, vector service or new Python dependency. Retrieval uses Arabic normalization, a small bilingual synonym dictionary, PostgreSQL GIN-indexed token overlap and deterministic ranking.
- This is lexical RAG, not semantic/vector search. Unseen paraphrases, Franco spellings and product ambiguity can reduce recall. It is intended for a small store corpus; matching candidates are ranked in Python.
- Generation still uses the configured model and its quota. Tool retrieval may add a model round trip. Offline and database tests never call it.
- Prices, stock, delivery fees and order mutations remain in transactional tools. Document text is reference data, not authority to change agent rules. Prompt instructions reduce injection/hallucination risk, but do not guarantee model compliance.
- Only trusted operators can import UTF-8 `.md`/`.txt` files through the CLI. There is no public upload endpoint, PDF parser, remote URL fetcher or customer-upload feature.

## Import locally with Docker

Run from the backend root after `docker compose up -d --build --wait` (which applies migrations). Find the existing demo seller; do not run seed to import knowledge:

```powershell
docker compose exec -T db psql -U yefhamak -d yefhamak -c "SELECT id, name FROM sellers;"
docker compose exec -T api python -m app.knowledge --seller-id YOUR_SELLER_UUID --file app/demo/knowledge/care.md --title "Demo garment care guide"
```

The bundled guide is explicitly fictional demo guidance, not product/manufacturer specifications. It intentionally does not invent organic-cotton claims. For your own file:

```powershell
docker compose cp .\my-guide.md api:/tmp/my-guide.md
docker compose exec -T api python -m app.knowledge --seller-id YOUR_SELLER_UUID --file /tmp/my-guide.md --title "Store care guide"
```

The filename is the stable source key. Reimporting the same filename for that seller atomically replaces its passages; another seller's document stays separate. Inputs are limited to 100,000 characters and split into passages of at most 1,000 characters. Use descriptive product names and keep each paragraph self-contained. Do not put current stock or prices in these files. Import only approved store facts. Updates appear on the next retrieval; past replies retain their original text and source names.

Example demo questions:

- «حسب دليل العناية، إزاي أغسل القطعة وأنشفها؟»
- «هل عندك دليل إن الهودي قطن عضوي؟» — should admit the missing specification and save a team question.
- «عندك شهادة مقاومة الحريق للهودي؟» — should not infer a certification from general care advice.

## Validation

Run `python -m unittest discover -s tests/unit -v` and the guarded `python -m tests.integration` with `TEST_DATABASE_URL` pointing to the disposable local database, as described in [database tests](database-tests.md). New tests cover normalization, passage limits, reference deduplication, isolation, replacement, missing results and a mocked model/tool/reply round trip. Live-model behavior is a separate check, not established by these deterministic tests.
