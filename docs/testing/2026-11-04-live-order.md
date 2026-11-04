# Live order verification — 2026-11-04

One synthetic customer order through the live FastAPI chat and seller endpoints, using OpenRouter’s `nvidia/nemotron-3-ultra-550b-a55b:free` model and PostgreSQL 16 in local Docker Compose.

1. **Catalog lookup passed.** The assistant found Basic Black Hoodie (`H-031`), black, size M, quoted EGP 380, and reported five available.
2. **Reservation and preview passed.** The customer confirmed the hold. The assistant showed one item at EGP 380 plus EGP 50 Cairo delivery, for a total of EGP 430.
3. **Customer checkout passed.** The customer approved the preview. The seller API listed one matching pending order (`7c13e9a0-62ab-41c5-842f-046ccd032cd1`). Its saved item, quantity, unit price, delivery fee, and total matched the preview.
4. **Seller confirmation passed.** The authenticated confirm endpoint returned `CONFIRMED`, and a subsequent order read returned the same status.
5. **Inventory reconciliation passed.** PostgreSQL showed stock `5 → 4` and reserved quantity `1 → 0` after seller confirmation.

**Result: 5/5 checkpoints passed (100%) in one live scenario.** This measures completion of this run. Broader reliability needs repeated scenarios. The verification used HTTP API requests, so browser interaction and recording remain separate. The assistant replied in Arabic to English test prompts. Synthetic checkout details are omitted from this record.
