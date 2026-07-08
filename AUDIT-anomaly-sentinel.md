# Prompt d'audit — Anomaly Sentinel (P1)

> À coller dans Claude Code, à la racine du repo, après un `/clear`.
> CLAUDE.md doit déjà être présent à la racine (il sera lu automatiquement).

---

Le projet est en statut COMPLETE (182/182 tests). Je ne veux AUCUNE réécriture, refactor ou "amélioration" de code sans validation explicite de ma part. Ta mission est un AUDIT en lecture, pas une intervention.

Objectif : vérifier qu'on n'est passé à côté de rien depuis la finalisation, et produire un rapport structuré (✅ solide / ⚠️ à surveiller / 🔧 correctif proposé — jamais appliqué sans mon accord).

Fais les vérifications suivantes, dans cet ordre, et rapporte les résultats réels (pas d'estimation) :

## 1. Suite de tests
- Lance `python -m pytest -v` et confirme 182/182 verts.
- Relance une deuxième fois pour détecter une éventuelle flakiness (résultat différent entre les deux runs = signal à remonter).
- Relève le temps d'exécution total.

## 2. Fallback déterministe
- Vérifie qu'aucune clé API n'est nécessaire : liste les endroits du code où un appel LLM est fait, confirme qu'un fallback rule-based existe pour chacun, et que la suite reste verte sans variable d'environnement de clé API définie.

## 3. Dépendances
- `pip list --outdated` : liste ce qui a évolué depuis la finalisation.
- Signale toute dépendance avec une CVE connue si tu peux le déterminer sans accès réseau supplémentaire non autorisé.

## 4. Secrets et hygiène repo
- Grep rapide pour toute clé API, token, ou credential qui aurait pu être committé par erreur.
- Vérifie que `.gitignore` couvre bien `.venv/`, les caches pytest, et tout artefact généré.

## 5. Cohérence documentaire
- Compare le README (nombre de tests annoncé, instructions de setup) avec l'état réel du repo. Signale tout écart.
- Vérifie que les ADRs dans `docs/adr/` correspondent toujours à ce qui est implémenté (pas de dérive architecture vs décision documentée).

## 6. Qualité résiduelle
- Cherche les `TODO`, `FIXME`, code commenté, ou blocs morts oubliés.
- Signale (sans les traiter) les éventuels tests trop permissifs ou assertions faibles.

## Livrable attendu

Un rapport unique, en anglais professionnel, sous forme de liste à puces par section (✅/⚠️/🔧). Pour chaque ⚠️ ou 🔧, propose une action mais **attends ma validation avant tout changement**. Si tout est vert, dis-le simplement — pas besoin d'inventer des problèmes.
