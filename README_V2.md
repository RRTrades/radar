# Radar v2 — mode recherche, filtrage strict et alertes à validation préalable

## Périmètre exact

- **Détection** : derniers profils DexScreener + indices de problèmes dans GitHub Issues (quotidien). Ce sont des **candidats non vérifiés**, jamais des preuves d'innovation.
- **Registre** : `problems_v2.json` est une hypothèse de départ maintenue par revue humaine. Les indices GitHub sont conservés dans `radar_v2_state.json`, pas automatiquement promus comme « problèmes non résolus ».
- **Alertes** : aucune alerte BUY sans fiche préalablement approuvée et non expirée dans `approved_projects.json`, identité `chain:contract` exacte, sécurité GoPlus et filtres de marché positifs.
- **Limites** : pas de jugement sémantique fiable, pas de comparaison concurrentielle automatisée vérifiée, ni preuve qu'un projet est *la* solution. Pas de garantie de timing ou de performance financière.

## Installation sans casser l'ancien radar

Ajouter `radar_v2.py`, `problems_v2.json`, `approved_projects.json`, `requirements-v2.txt`, `tests/test_radar_v2.py` et `.github/workflows/radar-v2.yml` dans le dépôt aux chemins indiqués. Conserver l'ancien `radar.py` et son workflow tels quels tant que la migration n'est pas approuvée. Attention : deux workflows tourneront et pourront consommer du quota GitHub Actions. Pour éviter cela, désactiver l'ancien workflow après vérification du nouveau, via GitHub Actions > radar > ... > Disable workflow.

Ne jamais placer de token Telegram dans un fichier. Les secrets existants sont utilisés. `radar-v2-research` se lance automatiquement aux minutes 7,27,47 et à 05:13 UTC (retards/omissions possibles sur GitHub Actions). Son premier démarrage ne doit **envoyer aucun BUY** parce que `approved_projects.json` vaut `[]`.

Pour lancer manuellement : GitHub > Actions > radar-v2-research > Run workflow. Conserver `dry_run=true` au premier test. Inspecter `radar_v2_report.json` dans l'artefact `radar-v2-diagnostic`, et `radar_v2_state.json` dans le dépôt après commit.

## Revue obligatoire avant approbation

Chaque candidat doit avoir une analyse datée du problème, des alternatives concurrentes, des preuves d'exécution, de l'utilité et de la capture de valeur par le token, de la distribution/vesting, des risques de contrat, d'équipe et de liquidité, et de la cohérence de l'adresse de contrat et de la chaîne. Les sources promotionnelles ne comptent pas comme preuves indépendantes. La décision doit être revue par un humain ; le moteur ne sait pas prouver ces points.

Les fiches approuvées doivent contenir : `name`, `symbol`, `chain`, `contract`, `problem_id`, `solution_keywords` (liste), `evidence_urls` (au moins deux), `competitor_comparison_url`, `reviewed_at`, `expires_at` (horodatages UTC ISO 8601) et les seuils `min_liquidity_usd`, `max_marketcap_usd`, `min_pair_age_hours`, `max_pair_age_hours`, `max_change_6h_pct`, `max_change_24h_pct`. Aucune entrée fictive n'est pré-approuvée. Les approbations expirent et doivent avoir été revues depuis moins de 14 jours.

## Mesure de qualité

Ne pas annoncer un « taux de précision » sans labels indépendants. Construire un jeu de cas historiques avec **dates de première information publique** et décisions aveugles, puis mesurer : précision des alertes, taux de détection des projets innovants (rappel), latence versus première preuve, faux positifs et rendement ajusté du risque. Évaluer aussi les projets **manqués** et la disponibilité réelle des données à l'époque.

## Sécurité / opérabilité

- Aucun ordre d'achat automatique.
- Rejet si données de marché requises manquantes, requête réseau en échec, sécurité indécidable ou identité de contrat ambiguë.
- Telegram confirmé `ok=true` avant mise à jour de l'état d'alerte ; en cas de panne, pas de fausse confirmation.
- `radar_v2_state.json` et `radar_v2_report.json` ne doivent contenir aucun secret.
- Une blockchain compatible Phantom n'assure ni la présence du token ni une route de swap ; la mention « disponibilité à vérifier » est volontaire.
- `max_pair_age_hours` mesure l'âge d'une **pool**, et non la date de création du token : il faudra compléter par de l'indexation on-chain avant toute prétention de détection très précoce.
- Règles GoPlus = contrôles limités, pas audit ni preuve d'absence de rug.

## Tests locaux

`pip install -r requirements-v2.txt && python -m unittest discover -s tests -v`

## Références

- https://docs.dexscreener.com/api/reference
- https://api-docs.defillama.com/
- https://docs.gopluslabs.io/reference/api-overview
- https://docs.github.com/en/actions/reference/events-that-trigger-workflows#schedule
