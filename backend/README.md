# DodgeAI Backend

FastAPI backend for DodgeAI.

## Demo data

There is no sample data in the repository. To try the graph views locally, load a small
synthetic Order-to-Cash dataset (10 customers, 24 products, 100 sales orders and the
deliveries, invoices, journal entries and payments downstream of them):

```bash
python scripts/seed_demo_data.py            # uses DATABASE_DSN / backend/.env
python scripts/seed_demo_data.py --reset    # wipe the O2C tables first
```

It creates the O2C tables if they are missing (not the pgvector `rag_embeddings` table, which
only the chat pipeline needs). The chat endpoint additionally needs `GEMINI_API_KEY`; without
it `POST /api/chat` answers with `error: "not_configured"`.
