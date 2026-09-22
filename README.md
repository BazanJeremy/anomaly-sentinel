# Anomaly Sentinel

**Framework de test pour IA de détection d'anomalies — valider un classifieur LLM
comme un composant critique, en medtech comme en fintech.**

[![CI](https://github.com/BazanJeremy/anomaly-sentinel/actions/workflows/ci.yml/badge.svg)](https://github.com/BazanJeremy/anomaly-sentinel/actions/workflows/ci.yml)
[![Tests](https://img.shields.io/badge/tests-182%20passing-brightgreen?logo=pytest)](tests/)
[![Python](https://img.shields.io/badge/python-3.11%20%7C%203.12-blue?logo=python)](requirements.txt)
[![License: MIT](https://img.shields.io/badge/license-MIT-lightgrey)](LICENSE)

> 🇬🇧 [English version](README.en.md)

## Le problème

Les classifieurs d'anomalies à base de LLM entrent en production dans des secteurs
où un faux négatif a un coût réel : une désaturation SpO₂ non signalée, une fraude
au virement non bloquée. Or ces composants sont non déterministes, et ils sont
rarement soumis à une stratégie de validation digne de ce nom. Anomaly Sentinel
répond à une question de QA : comment imposer des exigences déterministes —
précision, rappel, zéro alerte critique manquée — à un composant qui ne l'est pas ?

## Comment ça marche

Le classifieur IA est traité comme un **système sous test** — pas comme un outil qui
génère des tests. Chaque prédiction est validée par contrat, mesurée, et bloquée en
CI si elle passe sous les seuils.

Trois choix de stratégie de validation structurent le framework :

- **Fallback déterministe.** La suite complète (182 tests) tourne sans clé API. Si le
  LLM diverge des règles, un test échoue et déclenche une révision de prompt.
- **Prompts versionnés.** Un prompt est un artefact de configuration : chaque version
  (fintech `v1.0` et `v1.1`) doit passer les mêmes seuils sur le même corpus, et `v1.1`
  ne doit pas dégrader le taux de faux positifs de `v1.0` de plus de 5 points. Ces
  contrôles ne portent que sur le mode LLM : sans clé, aucun prompt n'est lu.
- **Observabilité qualité.** Précision, rappel et taux de faux positifs sont calculés
  à chaque run et affichés dans le dashboard ; en CI, leurs seuils font échouer la suite.

Cinq défauts réels ont été détectés par la suite de tests avant toute revue manuelle ;
un sixième a été trouvé plus tard, par la mesure et non par la suite — le détail est
documenté dans la [version anglaise](README.en.md).

## Architecture

```
  Simulateurs de scénarios étiquetés     6 scénarios cliniques + 6 typologies de
                 │                       fraude, labels attendus connus
                 ▼
  Contrats de données (Pydantic v2)      rejet des données invalides AVANT le LLM,
                 │                       identifiants directs retirés du contexte
                 ▼
  Classifieur double mode                Claude API si clé présente — sinon fallback
                 │                       à règles : une spécification exécutable du
                 ▼                       comportement attendu, pas un stub
  Quality gates mesurés en CI            précision ≥ 85 % · rappel ≥ 85 % · faux
                                         positifs ≤ 5 % · zéro alerte critique manquée
```

## Ce que ça détecte

### Medtech — surveillance de signes vitaux (contexte IEC 62304)

| Scénario | Événement clinique | Sévérité attendue |
|---|---|---|
| `spo2_desaturation` | SpO₂ < 90 % | critique |
| `hypertensive_crisis` | PA systolique ≥ 180 mmHg | haute |
| `bradycardia_event` | Fréquence cardiaque < 40 bpm | haute |
| `hypoglycaemia_alert` | Glycémie < 3,5 mmol/L | moyenne |
| `sensor_drift` | Batterie faible, oscillations non physiologiques | moyenne |
| `stable_routine` | Référence — aucune anomalie | — |

**Gate sécurité patient :** la désaturation SpO₂ doit être détectée 10 fois sur 10,
et un capteur dégradé ne doit jamais être classé en urgence clinique — les deux sont
des tests bloquants, pas des intentions.

### Fintech — surveillance transactionnelle (contexte PSD2 / AML)

| Scénario | Typologie de fraude | Sévérité attendue |
|---|---|---|
| `geo_impossible` | Changement de pays moins de 2 h après la transaction précédente | critique |
| `velocity_burst` | 15 transactions ou plus sur la journée | haute |
| `card_testing` | Micro-montant < 1 € sur appareil inconnu | haute |
| `dormant_account_spike` | Réactivation après 90 j ou plus, montant > 500 €, appareil inconnu | moyenne |
| `high_risk_category` | Crypto / jeux d'argent > 200 € sur profil retail | moyenne |
| `normal_purchase` | Référence — aucune anomalie | — |

Les typologies suivent les guidances publiques FATF et les rapports Europol sur la
criminalité financière.

## Stack technique

| Couche | Choix |
|---|---|
| Langage | Python 3.11 / 3.12 |
| Contrats de données | Pydantic v2 |
| Couche IA (optionnelle) | Anthropic Claude — `claude-sonnet-4-6` |
| Données de test | Faker |
| Framework de test | Pytest, pytest-playwright |
| Tests UI | Playwright (Chromium headless) |
| Dashboard | Flask 3 |
| CI | GitHub Actions — 3 jobs en matrice + un job de quality gate, check requis pour merger sur `main` (PR obligatoire, administrateurs compris) |
| Décisions d'architecture | ADR ([docs/](docs/)) |

## Démarrage rapide

```bash
git clone https://github.com/BazanJeremy/anomaly-sentinel.git
cd anomaly-sentinel
pip install -r requirements.txt
python -m playwright install chromium   # uniquement pour les tests UI

python -m pytest    # 182 tests — aucune clé API requise
```

La suite tourne intégralement en mode déterministe. Pour exercer le mode LLM,
définir `ANTHROPIC_API_KEY` et relancer la même commande.

Dashboard d'observabilité qualité (classification unitaire, batch, quality gate) :

```bash
python -m flask --app src/dashboard/app run --port 5000
# → http://localhost:5000
```

## Limites connues

Ce que le framework ne couvre pas, volontairement :

- **Données simulées.** Les flux sont générés (Faker) à partir de référentiels
  publics (OMS, FATF) — aucun flux de production réel.
- **Fallback heuristique.** Les règles spécifient le comportement attendu du LLM ;
  elles ne prétendent pas le remplacer en production.
- **Métriques LLM conditionnelles.** La CI publique valide le mode déterministe ;
  les métriques du mode LLM ne sont mesurées que lorsqu'une clé est fournie. Aucun
  run du mode LLM n'est publié dans ce dépôt à ce jour (voir l'amendement d'ADR-002).
- **Prompts en décalage avec les règles.** Les règles servent de spécification ; les
  prompts s'en écartent, et citent des critères que le contexte transmis ne permet pas
  d'évaluer.
  - Fintech `v1.1` : la distance entre deux pays (le contexte ne contient que leurs
    codes ; la règle regarde le changement de pays), une fenêtre de 2 h (le contexte ne
    compte que les transactions du jour), un compte dormant à plus de 90 j (la règle
    compte 90 j ou plus).
  - Medtech `v1.0` : un retard de calibration (absent du contexte), une batterie sous
    20 % (la règle inclut 20 %), une désaturation rapide limitée à SpO₂ < 94 % (la
    règle ne pose pas cette condition), une hypoglycémie « moyenne à haute » (la règle
    dit moyenne).

  Les aligner demandera de nouvelles versions de prompts, mesurées en mode LLM.
- **Pas de tests de charge** ni de flux temps réel — traitement par lots uniquement.

Pistes envisagées : un troisième secteur (télémétrie industrielle) sans modification
du classifieur — l'architecture adaptateur le permet (ADR-001) ; un re-run planifié
du corpus pour détecter la dérive du modèle ; un export de rapport d'audit horodaté
pour la traçabilité réglementaire.

## Projets associés

Ces outils partagent les mêmes principes : **le déterministe d'abord, l'IA là où elle apporte — le QA reste l'arbitre.** Tous tournent en local, aucune clé API requise.

| Projet | Focus |
|---|---|
| [EvalForge](https://github.com/BazanJeremy/EvalForge) | Évaluation de LLM & calibration du juge |
| [ReleaseGuard](https://github.com/BazanJeremy/ReleaseGuard) | Verrou de release GO/NO-GO explicable |
| [FlakySense](https://github.com/BazanJeremy/flakysense) | Diagnostic statistique des tests flaky |
| [Anomaly Sentinel](https://github.com/BazanJeremy/anomaly-sentinel) **← ce repo** | Tester les IA de détection d'anomalies (medtech · fintech) |
| [TestScribe](https://github.com/BazanJeremy/testscribe) | Enrichissement de bug reports assisté par IA |
| [SkyGuard](https://github.com/BazanJeremy/skyguard) | Quality gate sécurité pour systèmes critiques avioniques |

## Auteur

**Jérémy Bazan** — Ingénieur QA / Lead Tech QA, spécialisation AI-driven Quality.
ISTQB Foundation v4. Intégration de LLM (Claude, GPT) dans des pipelines QA de
production au sein d'un grand groupe du secteur de l'énergie.

[LinkedIn](https://www.linkedin.com/in/jeremy-bazan/) · [GitHub](https://github.com/BazanJeremy)
