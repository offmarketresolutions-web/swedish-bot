# General-knowledge FAQ package

`nordland-general-knowledge.json` is the 102-entry conversation-derived corpus
(92 category FAQs + 10 site FAQs), in the shape `import_general_knowledge` reads.

It lives in the repo because it has no other home: the originally distributed
`.zip` was lost, so for a while the only copy was a single dev Postgres volume —
which is why a fresh production deploy came up with 1 FAQ entry instead of 93.
`post_deploy` now imports this file by default, so any rebuild self-heals.

Regenerate it from a database that has the corpus:

    python manage.py export_general_knowledge data/general_knowledge/nordland-general-knowledge.json

Every row imports **unapproved**. Approval is the owner's editorial act in the
dashboard and is deliberately not carried in the package — re-importing never
un-approves a row the owner already approved.
