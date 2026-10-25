# DodgeAI Backend

FastAPI backend and the `graphsense` operator CLI for DodgeAI. See the repository `CLAUDE.md` for the architecture.

## Demo data

There is no sample data in the repository. To try the graph views locally, generate a small
synthetic Order-to-Cash dataset in the raw export shape and load it:

```bash
graphsense db migrate
python scripts/make_demo_data.py --out /tmp/demo-data
graphsense ingest o2c --data-root /tmp/demo-data
```

Ingestion creates the dataset's tables in the `ds_o2c` schema from the package; migrations
never create dataset tables. The Ask endpoint additionally needs `GEMINI_API_KEY`; without
it `POST /api/chat` answers with `error: "not_configured"`.
