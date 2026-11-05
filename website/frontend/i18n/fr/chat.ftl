# Translation of en/chat.ftl. Change it together with the English catalog.

chat-activity-the-bot-is-working = L’assistant travaille...
chat-composer-ask-the-bot = Posez votre question à l’assistant...
chat-composer-internet-tools = Outils Internet
chat-composer-agent-language-title = L’agent répond en { $language }. Changez la langue dans les paramètres, dans un nouvel onglet.
chat-composer-try-again-in-s = Réessayez dans { $secs } s
chat-composer-stop-the-answer-the-partial = Arrêter la réponse (la réponse partielle n’est pas enregistrée dans la conversation)
chat-composer-starting-the-conversation-u = Démarrage de la conversation…
chat-composer-send = Envoyer
chat-conversation-find-search-in-conversation = Rechercher dans la conversation
chat-conversation-find-previous-match = Correspondance précédente
chat-conversation-find-next-match = Correspondance suivante
chat-conversation-find-investigation-board = Tableau d’enquête
doc-ref-card-not-openable = Ouverture impossible : { $reason }.
doc-ref-card-the-search-term-was = Le terme recherché était{" "}
doc-ref-card-open = Ouvrir
doc-ref-card-not-openable-2 = Ouverture impossible
chat-markdown-text-show-the-cited-source = Afficher la source citée
chat-markdown-text-no-citation-of-this-conversation = Aucune citation de cette conversation n’a attribué ce repère, donc aucun document n’y correspond.
chat-markdown-text-citations-of-this-conversation-gave = Les citations de cette conversation ont attribué ce repère à plusieurs documents, donc il ne mène à aucun d’eux.
cards-browser-card-open-the-archived-page = Ouvrir la page archivée
cards-browser-card-the-page-itself-was-not = La page elle-même n’a pas été archivée (statut : { $artifact_status }). La capture d’écran ci-dessus est ce qui a été conservé.
cards-browser-card-click-the-screenshot-to-open = Cliquez sur la capture d’écran pour ouvrir la page archivée.
cards-browser-card-show-less = Afficher moins
cards-browser-card-show-all = Tout afficher
cards-browser-card-archived-page = Page archivée
cards-browser-card-download = Télécharger
cards-browser-card-archived-copy-of = Copie archivée de { $artifact_url }
cards-browser-card-this-page-was-not-archived = Cette page n’a pas été archivée (statut : { $artifact_status }).
cards-entities-card-with-a-card = { $openable } avec fiche
cards-entities-card-the-entity-list-was-cut = La liste d’entités a été tronquée.
cards-entities-card-open-the-card-for-this = Ouvrir la fiche de cette valeur ({ $rule_id })
cards-entities-card-no-card-this-conversation-never = Pas de fiche : cette conversation n’a jamais nommé le jeu de données d’où viennent ces valeurs, et la visionneuse s’ouvre par jeu de données.
cards-entities-card-more-all-of-them-in = { $rest } autres, toutes dans le volet des entités du document.{" "}
cards-entities-card-names-organisations-and-places-above = Les noms, organisations et lieux ci-dessus sont la lecture du texte par un modèle. Aucune règle ne les a validés : il n’y a rien à expliquer et ils n’ouvrent rien.
cards-entities-card-nothing-extracted-from-this-document = Rien n’a été extrait de ce document.
chat-tool-cards-hide = Masquer
chat-tool-cards-expand = Développer
chat-tool-cards-hide-raw-json = Masquer le JSON brut
chat-tool-cards-show-raw-json = Afficher le JSON brut
cards-result-cards-search-this = Rechercher ceci
cards-result-cards-search-every-collection = Rechercher dans toutes les collections
cards-result-cards-form = Variante { $index } : { $form }
cards-result-cards-show-full-text = Afficher le texte complet
cards-result-cards-quote = Extrait : { $quote }
cards-result-cards-reason = Raison : { $why }
cards-result-cards-open-question = Question ouverte : { $question }
cards-result-cards-the-explore-gave-this-answer = L’exploration a donné cette réponse à son tableau d’enquête sous la forme d’un constat { $kind ->
        [sourced] sourcé
        [inferred] déduit
        [not_found] « non trouvé »
       *[other] de type inconnu
    }.
cards-result-cards-it-left-no-open-question = Elle n’a laissé aucune question ouverte.
cards-result-cards-open-questions-for-the-board = Questions ouvertes pour le tableau d’enquête :
cards-result-cards-arguments = Arguments
cards-result-cards-list-after-the-call = Liste après l’appel : { $snapshot_goal }
cards-result-cards-replaces = {" "}· remplace { $replaces_id }
cards-result-cards-the-list-at-this-version = La liste de cette version n’est pas enregistrée.
web-search-card-these-sources-returned-nothing-so = Ces sources n’ont rien renvoyé : les résultats viennent de moins de sources que prévu
web-search-card-u-degraded = ⚠ { $degraded_len } dégradée(s)
web-search-card-form = Variante { $index } : { $form }
web-search-card-no-results-from = Aucun résultat de : { $degraded_text }
web-search-card-no-results-every-source-answered = Aucun résultat. Toutes les sources ont répondu et aucune n’avait rien pour cette requête.
web-search-card-the-lowest-ranked-results-were = Les résultats les moins bien classés ont été retirés pour que cet appel tienne dans la transcription. L’assistant les a tous vus.
web-search-card-view-search-details = Voir les détails de la recherche.
web-search-card-the-stored-result-could-not = le résultat enregistré n’a pas pu être relu en JSON
web-search-card-nothing-was-stored-for-this = Rien n’a été enregistré pour cet appel.
web-search-card-forms = Variantes : { $forms }
web-search-card-kind = Type : { $row_kind }
web-search-card-published = Publié : { $row_published }
web-search-card-loading-search-detail-u = Chargement des détails de la recherche…
web-search-card-could-not-load-the-search = Impossible de charger les détails de la recherche : { $e }
web-search-card-malformed-detail = Détail mal formé : { $e }
web-search-card-the-tool-returned-selected-results = L’outil a renvoyé au modèle des résultats sélectionnés.
web-search-card-results-use-reciprocal-rank-fusion = Les résultats utilisent la fusion de rangs réciproques.
web-search-card-returned-nothing = n’a rien renvoyé : { $degraded }
web-search-card-all-candidates-use-fusion-order = Tous les candidats suivent l’ordre de fusion.
web-search-card-the-cross-encoder-ranks-selected = Le cross-encoder classe les résultats sélectionnés.
web-search-card-selected-results-use-fusion-order = Les résultats sélectionnés suivent l’ordre de fusion.
web-search-card-search-detail = Détails de la recherche
web-search-card-rrf = RRF n° { $row_rrf_rank }
chat-tool-disclosure-search-this = Rechercher ceci
chat-tool-disclosure-search-every-collection = Rechercher dans toutes les collections
chat-tool-disclosure-hide = Masquer
chat-tool-disclosure-expand = Développer
chat-tool-disclosure-this-step-was-recorded-before = Cette étape a été enregistrée avant que les arguments et les résultats des outils soient conservés. Seul le résumé ci-dessous est disponible.
chat-tool-disclosure-arguments = Arguments
chat-tool-disclosure-result = Résultat
chat-tool-disclosure-hide-raw-json = Masquer le JSON brut
chat-tool-disclosure-show-raw-json = Afficher le JSON brut
chat-tool-disclosure-input-json = JSON d’entrée
chat-tool-disclosure-output-json = JSON de sortie
chat-transcript-ask-a-question-about-the = Posez une question sur les documents de vos collections.
chat-transcript-suggested-next = Suites suggérées...
chat-transcript-earlier-answer = Réponse précédente
chat-transcript-tokens-the-conversation-carries-the = Jetons portés par la conversation, plus grand contexte unique facturé pour ce tour, et part de la fenêtre du modèle qu’il a utilisée
chat-transcript-instruction-to-the-agent = Instruction à l’agent
chat-transcript-the-context-stays-above-the = {" "}Le contexte reste au-dessus de l’objectif de { $target }.
chat-transcript-summary-parts-failed-the-record = {" "}{ $failed } parties du résumé ont échoué. Le registre ne contient que les listes.
chat-transcript-show-the-record = Afficher le registre
chat-transcript-hide-reasoning = Masquer le raisonnement
chat-transcript-show-reasoning = Afficher le raisonnement
chat-transcript-from-u-hide = { $count } { $count ->
        [one] document
       *[other] documents
    } de { $tool } — masquer
chat-transcript-from-u-show = { $count } { $count ->
        [one] document
       *[other] documents
    } de { $tool } — afficher
chat-transcript-u-hide = { $summary } — masquer
chat-transcript-u-show = { $summary } — afficher
chat-transcript-citations-of-this-conversation-give = Les citations de cette conversation donnent le repère { $doc_handle } à plusieurs documents. La réponse ne le relie à aucun d’eux.
chat-transcript-report = Rapport { $label }
chat-transcript-open-in-the-workspace = Ouvrir dans l’espace de travail
chat-transcript-this-version-could-not-be = Cette version n’a pas pu être lue. Le texte de la réponse dans le chat suit.
chat-transcript-files = Fichiers
chat-transcript-version = { $file_name }, version { $file_version }
chat-web-find-exact-text = Rechercher le texte exact
chat-web-previous-match = Correspondance précédente
chat-web-next-match = Correspondance suivante
chat-web-close-preview = Fermer l’aperçu
chat-web-the-captured-page-could-not = La page capturée n’a pas pu être chargée.
chat-web-loading = Chargement…
chat-workspace-pane-workspace = Espace de travail
chat-workspace-pane-close-the-workspace = Fermer l’espace de travail
chat-workspace-pane-close = Fermer
chat-workspace-pane-loading-the-files-u = Chargement des fichiers…
chat-workspace-pane-the-files-could-not-be = Les fichiers n’ont pas pu être chargés : { $error }
chat-workspace-pane-this-conversation-has-no-files = Cette conversation n’a aucun fichier.
chat-workspace-pane-version = version { $entry_version }, { $length_text_entry_chars }
chat-workspace-pane-choose-a-file-to-read = Choisissez un fichier pour le lire.
chat-workspace-pane-loading-the-file-u = Chargement du fichier…
chat-workspace-pane-the-file-could-not-be = Le fichier n’a pas pu être chargé : { $error }
chat-workspace-pane-version-2 = { $found_name }, version { $found_version }
chat-board-create-collections = Collections
chat-board-create-loading-collections-u = Chargement des collections…
chat-board-create-hoover-search-new-board = Hoover Search - Nouveau tableau d’enquête
chat-board-create-ai-chat = Chat IA
chat-board-create-new-investigation-board = Nouveau tableau d’enquête
chat-board-create-a-board-runs-its-goals = Un tableau d’enquête traite ses objectifs sous forme d’une suite d’explorations de l’agent. Chaque exploration est une conversation qui aboutit à un constat du tableau. Vous relisez la réponse de chaque objectif, et vous pouvez rejeter des constats et ajouter des indices pendant l’exécution.
chat-board-create-title = Titre
chat-board-create-goal = Objectif
chat-board-create-remove-this-goal = Supprimer cet objectif
chat-board-create-remove = Supprimer
chat-board-create-add-a-goal = Ajouter un objectif
chat-board-create-context-optional = Contexte (facultatif)
chat-board-create-hints-one-per-line-optional = Indices, un par ligne (facultatif)
chat-board-create-sources = Sources
chat-board-create-internet-tools = Outils Internet
chat-board-create-creating-board = Création du tableau d’enquête...
chat-board-create-create-board = Créer le tableau d’enquête
ai-chat-board-hoover-search-board = Hoover Search - Tableau d’enquête
ai-chat-board-loading-the-board-u = Chargement du tableau d’enquête…
ai-chat-board-show-the-board-overview = Afficher l’aperçu du tableau d’enquête
ai-chat-board-zoom-out = Zoom arrière
ai-chat-board-zoom-in = Zoom avant
ai-chat-board-u-ai-chat = ← Chat IA
ai-chat-board-settings = Réglages
ai-chat-board-board-settings = Réglages du tableau d’enquête
ai-chat-board-internet-tools = Outils Internet
ai-chat-board-the-next-explores-of-the = Les prochaines explorations du tableau d’enquête peuvent chercher sur le Web et lire des pages Web. Les explorations en cours gardent le réglage avec lequel elles ont démarré.
ai-chat-board-collections = Collections
ai-chat-board-the-collections-are-fixed-when = Les collections sont fixées à la création du tableau d’enquête.
ai-chat-board-confirm-drop = Confirmer l’abandon
ai-chat-board-drop-the-board = Abandonner le tableau d’enquête
ai-chat-board-close = Fermer
ai-chat-board-the-board-used-its-explore = Le tableau d’enquête a atteint sa limite d’explorations
ai-chat-board-the-board-used-explores-the = Le tableau d’enquête a utilisé { $explore_limit } explorations, la limite d’un tableau. Il ne lance plus de travail. Vous pouvez encore trancher les réponses proposées.
ai-chat-board-create-a-new-board-to = Créez un nouveau tableau d’enquête pour poursuivre l’enquête
ai-chat-board-goal = Objectif
ai-chat-board-goals = Objectifs
ai-chat-board-add-new-goal = Ajouter un nouvel objectif...
ai-chat-board-a-new-goal = Un nouvel objectif
ai-chat-board-add-goal = Ajouter l’objectif
ai-chat-board-a-board-has-at-most = Un tableau d’enquête compte { $max_goals } objectifs au maximum. Créez un nouveau tableau d’enquête pour un autre objectif.
ai-chat-board-background-context = Contexte
ai-chat-board-continue-with-a-correction = Poursuivre avec une correction
ai-chat-board-correction-what-is-wrong-or = Correction : ce qui est faux ou manque. Le tableau d’enquête poursuit avec elle.
ai-chat-board-the-board-waits-for-your = Le tableau d’enquête attend votre relecture
ai-chat-board-the-board-used-its-budget = Le tableau d’enquête a utilisé son budget de { $snap_max_explores } explorations.
ai-chat-board-the-assessments-gave-no-usable = Les évaluations n’ont donné aucune direction exploitable.
ai-chat-board-accept-or-reject-the-proposed = Acceptez ou rejetez la réponse proposée pour chaque objectif ci-dessus. Une réponse rejetée permet au tableau d’enquête de continuer aussitôt.
ai-chat-board-no-proposed-answer-waits-for = Aucune réponse proposée n’attend votre décision.
ai-chat-board-reopen-the-board-to-continue = Rouvrez le tableau d’enquête pour poursuivre les objectifs ouverts. Il conserve ses constats et ses réponses.
ai-chat-board-close-the-board-to-accept = Fermez le tableau d’enquête pour accepter toutes les réponses proposées et l’arrêter, ou poursuivez-le avec une correction.
ai-chat-board-close-the-board = Fermer le tableau d’enquête
ai-chat-board-or-reopen-the-board-to = Ou rouvrez le tableau d’enquête pour poursuivre les objectifs ouverts sans correction.
ai-chat-board-the-board-is-complete = Le tableau d’enquête est complet
ai-chat-board-a-goal-has-no-accepted = Un objectif n’a pas de réponse acceptée. Rouvrez le tableau d’enquête pour le poursuivre. Le tableau conserve ses constats et ses réponses.
ai-chat-board-add-a-hint = Ajouter un indice
ai-chat-board-the-next-assessment-reads-every = La prochaine évaluation lit tous les indices. Un indice répond aussi à une exploration qui a posé une question.
ai-chat-board-add-hint = Ajouter l’indice
ai-chat-board-events = Événements
ai-chat-board-newest-first = Plus récents d’abord
ai-chat-board-date = Date
ai-chat-board-actor = Acteur
ai-chat-board-event = Événement
ai-chat-board-show-details = Afficher les détails
ai-chat-board-open = Ouvrir
ai-chat-board-show-the-newest-events = Afficher les { $event_rows } événements les plus récents
ai-chat-board-show-all-events = Afficher les { $snap_events_len } événements
ai-chat-board-statistics = Statistiques
ai-chat-board-explores = Explorations
ai-chat-board-model-steps-per-explore = Étapes du modèle par exploration
ai-chat-board-assessments = Évaluations
ai-chat-board-intents = Intentions
ai-chat-board-findings = Constats
ai-chat-board-created = Créé
ai-chat-board-rejected-this-finding-on-the = { $rejected_by } a rejeté ce constat le { $format_utc_ms_fact_rejected_ms }. Le tableau d’enquête ne l’utilise plus.
ai-chat-board-rejected-this-finding-the-board = { $rejected_by } a rejeté ce constat. Le tableau d’enquête ne l’utilise plus.
ai-chat-board-no-reason-was-given = Aucune raison n’a été indiquée.
ai-chat-board-reason = Raison : { $fact_rejected_reason }
ai-chat-board-open-questions = Questions ouvertes
ai-chat-board-explored-in = Exploré dans{" "}
ai-chat-board-explore-this-question = Explorer cette question
ai-chat-board-your-questions = Vos questions
ai-chat-board-ask-about-the-background-context = Poser une question sur le contexte
ai-chat-board-ask-about-this-finding = Poser une question sur ce constat
ai-chat-board-a-follow-up-question-about = Une question complémentaire sur ce nœud
ai-chat-board-ask = Demander
ai-chat-board-checks-that-changed-this-finding = Vérifications qui ont modifié ce constat
ai-chat-board-reject-this-correction = Rejeter cette correction
ai-chat-board-reject-this-finding = Rejeter ce constat
ai-chat-board-not-answered-the-board-was = Sans réponse. Le tableau d’enquête a été terminé sans réponse pour cet objectif. Un indice ou une réouverture le rouvre.
ai-chat-board-no-answer-yet = Pas encore de réponse.
ai-chat-board-the-findings-of-this-answer = Les constats de cette réponse sont des recherches qui n’ont rien trouvé. Acceptez-la pour consigner que les enregistrements ne répondent pas à l’objectif, ou rejetez-la pour poursuivre l’enquête.
ai-chat-board-open-an-assessment-to-read = {"."} Ouvrez une évaluation pour en lire la raison.
ai-chat-board-from-the-findings = À partir des constats{" "}
ai-chat-board-accept-answer = Accepter la réponse
ai-chat-board-why-the-answer-is-wrong = Pourquoi la réponse est fausse ou incomplète
ai-chat-board-reject-answer = Rejeter la réponse
ai-chat-board-intent = Intention
ai-chat-board-attempts-declared = Tentatives : { $intent_attempts }. Déclarée le { $format_utc_ms_intent_created_ms }.
ai-chat-board-the-explore-asked = L’exploration a demandé
ai-chat-board-add-a-hint-in-the = Ajoutez un indice dans l’aperçu du tableau d’enquête pour y répondre.
ai-chat-board-last-error = Dernière erreur
ai-chat-board-brief = Consigne
ai-chat-board-open-the-explore-chat = Ouvrir la conversation d’exploration
ai-chat-board-loading-the-assessment-u = Chargement de l’évaluation…
ai-chat-board-assessment = Évaluation { $reason_no }
ai-chat-board-model-outcome-ms = { $format_utc_ms_a_created_ms }. Modèle { $a_model }. Résultat { $a_outcome }. { $a_latency_ms } ms, { $tokens }.
ai-chat-board-checks-that-changed-it = Vérifications qui l’ont modifié
ai-chat-board-prompt = Prompt
ai-chat-board-this-assessment-ran-before-the = Cette évaluation a eu lieu avant l’enregistrement des prompts.
ai-chat-board-response = Réponse
ai-chat-history-hoover-search-chat-history = Hoover Search - Historique des conversations
ai-chat-history-u-back = ← Retour
ai-chat-history-conversation-history = Historique des conversations
ai-chat-history-show-board-chats = Afficher les conversations des tableaux d’enquête
ai-chat-history-loading-u = Chargement…
ai-chat-history-could-not-load-history = Impossible de charger l’historique : { $e }
ai-chat-history-no-conversations-yet = Aucune conversation pour le moment.
ai-chat-history-board = Tableau d’enquête
ai-chat-history-new-chat = Nouvelle conversation
ai-chat-history-messages-updated = { $s_message_count ->
    [one] { $s_message_count } message · mise à jour { $s_updated_at }
    *[other] { $s_message_count } messages · mise à jour { $s_updated_at }
    }

ai-chat-history-delete-conversation = Supprimer la conversation
ai-chat-history-delete = Supprimer
ai-chat-homepage-hoover-search-ai-chat = Hoover Search - Chat IA
ai-chat-homepage-what-are-you-researching = Sur quoi portent vos recherches ?
ai-chat-homepage-view-all-conversations = Voir toutes les conversations
ai-chat-homepage-starting-conversation-u = Démarrage de la conversation…
ai-chat-homepage-investigation-boards = Tableaux d’enquête
ai-chat-homepage-new-board = Nouveau tableau d’enquête
ai-chat-homepage-loading-boards-u = Chargement des tableaux d’enquête…
ai-chat-homepage-could-not-load-the-boards = Impossible de charger les tableaux d’enquête : { $user_facing_message_e }
ai-chat-homepage-you-have-no-board-a = Vous n’avez aucun tableau d’enquête. Un tableau d’enquête mène une longue enquête sous forme d’une suite d’explorations de l’agent, et vous en relisez les réponses.
ai-chat-homepage-updated = Mis à jour { $format_utc_ms_board_updated_ms }
ai-chat-session-hoover-search-ai-chat = Hoover Search - Chat IA
ai-chat-session-this-conversation-could-not-be = Cette conversation n’a pas pu être chargée.
ai-chat-session-loading-u = Chargement…
ai-chat-session-u-chats = ← Conversations
ai-chat-session-history = Historique
ai-chat-session-show-the-files-that-the = Afficher les fichiers que l’assistant a écrits dans cette conversation
ai-chat-session-workspace = Espace de travail
ai-chat-session-this-answer-was-interrupted-before = Cette réponse a été interrompue avant la fin, parce que la page ou le serveur s’est arrêté en cours de tour. Posez la question à nouveau pour réessayer.
ai-chat-session-dismiss = Ignorer
ai-chat-session-board-explore-chats-are-read = Les conversations d’exploration d’un tableau d’enquête sont en lecture seule.{" "}
ai-chat-session-open-the-board = Ouvrir le tableau d’enquête
chat-locked-options-on = { $label } : activé
chat-locked-options-off = { $label } : désactivé
chat-tool-cards-running-u = en cours…
cards-result-cards-quote-found = Extrait trouvé
cards-result-cards-quote-not-found = Extrait introuvable
cards-result-cards-quote-not-checked = Extrait non vérifié
web-search-card-results = { $results_len } résultats
chat-tool-disclosure-running-u = en cours…
chat-transcript-call = appel
chat-transcript-calls = appels
ai-chat-board-a-board-without-collections-needs = Un tableau d’enquête sans collection a besoin des outils Internet.
ai-chat-board-of = { $snap_explores_used } sur { $snap_max_explores }
ai-chat-board-assessment-2 = évaluation { $number }
ai-chat-history-messages = { $s_message_count ->
    [one] { $s_message_count } message
    *[other] { $s_message_count } messages
    }

web-search-card-reranked-in = Le cross-encoder a classé les résultats en { $ms } ms.
web-search-card-engine-results = { $name } : { $count } en { $ms } ms
web-search-card-score-was-rank = score { $score } · était RRF n° { $rank }
chat-activity-the-turn-waits-for-a = Le tour attend un emplacement libre pour le modèle.
chat-activity-the-turn-waits-for-a-2 = Le tour attend un emplacement libre pour les outils.
chat-locked-options-start-a-new-chat-to = Démarrez une nouvelle conversation pour modifier ce réglage.
chat-locked-options-internet-tools = Outils Internet
chat-session-card-new-chat = Nouvelle conversation
chat-tool-cards-first-frame-of-the-video = Première image de la vidéo
chat-tool-cards-screenshot-of = Capture d’écran de
chat-tool-cards-image = Image
cards-result-cards-the-agent-asked-a-question = L’agent a posé une question.
chat-transcript-hide = Masquer
chat-transcript-show = Afficher
chat-transcript-unverified-quote-the-quoted-span = Extrait non vérifié. Le passage cité est trop court pour être vérifié.
chat-transcript-unverified-quote-the-document-text = Extrait non vérifié. Le texte du document n’a pas pu être lu.
chat-transcript-unverified-quote-this-wording-was = Extrait non vérifié. Cette formulation n’a pas été trouvée dans le document.
chat-board-create-select-a-collection-or-turn = Sélectionnez une collection ou activez les outils Internet.
chat-board-create-select-at-least-one-collection = Sélectionnez au moins une collection.
ai-chat-board-active = Actif
ai-chat-board-paused = En pause
ai-chat-board-waits-for-review = En attente de relecture
ai-chat-board-completed = Terminé
ai-chat-board-dropped = Abandonné
ai-chat-board-unknown = Inconnu
ai-chat-board-pause-the-board = Mettre le tableau d’enquête en pause
ai-chat-board-resume-the-board = Reprendre le tableau d’enquête
ai-chat-board-none = Aucun
ai-chat-board-reopen-with-the-remaining-budget = Rouvrir avec le budget restant
ai-chat-board-finding = Constat
ai-chat-board-why-the-correction-is-wrong = Pourquoi la correction est fausse
ai-chat-board-reject-correction = Rejeter la correction
ai-chat-board-why-the-finding-is-wrong = Pourquoi le constat est faux
ai-chat-board-reject-finding = Rejeter le constat
ai-chat-board-answer = Réponse
ai-chat-board-proposed-answer = Réponse proposée
ai-chat-homepage-active = Actif
ai-chat-homepage-paused = En pause
ai-chat-homepage-waits-for-review = En attente de relecture
ai-chat-homepage-completed = Terminé
ai-chat-homepage-dropped = Abandonné
ai-chat-homepage-unknown = Inconnu
cards-result-cards-submitted-by-board = Soumis par le tableau d’enquête : constat { $kind ->
        [sourced] sourcé
        [inferred] déduit
        [not_found] « non trouvé »
       *[other] de type inconnu
    } issu du rapport
cards-result-cards-finding-for-board = Constat { $kind ->
        [sourced] sourcé
        [inferred] déduit
        [not_found] « non trouvé »
       *[other] de type inconnu
    } pour le tableau d’enquête
chat-transcript-compacting = Compactage du contexte : de { $before } jetons vers un objectif de { $target }.
chat-transcript-compaction-failed = Le résumé des étapes précédentes a échoué. Le modèle a reçu les étapes précédentes sans modification, { $after } jetons.
chat-transcript-compacted = Contexte compacté : { $steps } étapes résumées, de { $before } à { $after } jetons.
ai-chat-board-reopen-with-more = Rouvrir avec { $grant } explorations de plus
ai-chat-board-goal-number = Objectif { $number }
ai-chat-board-from-assessment-on = D’après l’évaluation { $number } du { $date }.
ai-chat-board-from-assessment = D’après l’évaluation { $number }.
chat-board-create-goal-2 = Objectif { $index_1 }
ai-chat-session-lost-contact-with-the-chat = contact perdu avec le chat : { $e }
ai-chat-session-could-not-stop-the-answer = impossible d’arrêter la réponse : { $e } — elle est toujours en cours
ai-chat-board-later-assessments-dropped-an-answer = { $n } évaluation(s) ultérieure(s) ont écarté une réponse pour cet objectif :
ai-chat-board-prompt-and-completion-tokens = { $a_prompt_tokens } jetons de prompt et { $a_completion_tokens } jetons de complétion
ai-chat-homepage-completed-goals-not-answered = Terminé, { $n } objectifs sans réponse
board-graph-intent = intention, { $state }
chat-workspace-pane-characters = { $chars } caractères
chat-transcript-running-tool = { $tool_run_summary_messages_start_end_run_ } + { $joined_live_end } { $if_joined_live_end_1_tr_chat_transcript_ } d’outil en cours
chat-transcript-running-tool-2 = { $turn_tool_rows_len } { $if_turn_tool_rows_len_1_tr_chat_transcri } d’outil en cours
chat-transcript-answered-after-failed-attempt = Réponse obtenue après { $retries_len } { $retries_len ->
        [one] tentative échouée
       *[other] tentatives échouées
    }{ $if_retries_len_1_else_s ->
       *[other] {""}
    }
chat-transcript-failed-attempt = { $retries_len } { $retries_len ->
        [one] tentative échouée
       *[other] tentatives échouées
    }{ $if_retries_len_1_else_s ->
       *[other] {""}
    }
chat-transcript-version-2 = { $report_name }, version { $report_version }
tool-run-summary-searched = { $n ->
        [one] { $n } terme recherché
       *[other] { $n } termes recherchés
    }
tool-run-summary-read = { $n ->
        [one] { $n } document lu
       *[other] { $n } documents lus
    }
tool-run-summary-searched-the-web-for = { $n ->
        [one] { $n } terme recherché sur le Web
       *[other] { $n } termes recherchés sur le Web
    }
tool-run-summary-read-web = { $n ->
        [one] { $n } page Web lue
       *[other] { $n } pages Web lues
    }
tool-run-summary-browser = { $n ->
        [one] { $n } action du navigateur
       *[other] { $n } actions du navigateur
    }
tool-run-summary-listed-the-entities-of = { $n ->
        [one] entités de { $n } document listées
       *[other] entités de { $n } documents listées
    }
tool-run-summary-cited = { $n ->
        [one] { $n } document cité
       *[other] { $n } documents cités
    }
tool-run-summary-cited-web = { $n ->
        [one] { $n } page Web citée
       *[other] { $n } pages Web citées
    }
tool-run-summary-read-and-tool-texts = { $n ->
        [one] { $n } compétence et textes d’outils lus
       *[other] { $n } compétences et textes d’outils lus
    }
tool-run-summary-saved = { $n ->
        [one] { $n } note enregistrée
       *[other] { $n } notes enregistrées
    }
tool-run-summary-todo-list = { $n ->
        [one] { $n } appel de liste de tâches
       *[other] { $n } appels de liste de tâches
    }
tool-run-summary-to-the-agent = { $n ->
        [one] { $n } instruction à l’agent
       *[other] { $n } instructions à l’agent
    }
tool-run-summary-other = { $n ->
        [one] { $n } autre appel
       *[other] { $n } autres appels
    }
tool-run-summary-failed = { $failures } en échec
tool-run-summary-took = durée : { $duration_text_ms }
chat-session-card-messages = { $session_message_count ->
    [one] { $session_message_count } message
    *[other] { $session_message_count } messages
    }

chat-tool-disclosure-item = { $count ->
        [one] { $count } élément
       *[other] { $count } éléments
    }
chat-tool-disclosure-field = { $count ->
        [one] { $count } champ
       *[other] { $count } champs
    }
chat-tool-disclosure-searched-collections = collections interrogées{ $filters }
chat-tool-disclosure-searched-collections-2 = collections interrogées · { $query }{ $filters }
chat-tool-disclosure-cited-documents = { $n } documents cités
chat-tool-disclosure-read-document = document lu · { $path }
chat-tool-disclosure-searched-the-web = recherche Web · { $q }
chat-tool-disclosure-opened-page = page ouverte · { $u }
chat-tool-disclosure-whois = whois · { $d }
chat-tool-disclosure-called = appel de { $other }
chat-tool-disclosure-called-2 = appel de { $other } · { $short }
cards-browser-card-opened = { $url } ouvert
cards-browser-card-could-not-open = impossible d’ouvrir { $url }
cards-browser-card-clicked = clic sur { $element }
cards-browser-card-could-not-click = clic impossible sur { $element }
cards-browser-card-typed-into = saisie dans { $element }
cards-browser-card-could-not-type-into = saisie impossible dans { $element }
cards-browser-card-typed = saisie de « { $text } »
cards-browser-card-could-not-type = saisie impossible de « { $text } »
cards-browser-card-pressed = touche { $key } pressée
cards-browser-card-could-not-press = impossible d’appuyer sur { $key }
cards-browser-card-chose-an-option-in = option choisie dans { $element }
cards-browser-card-could-not-choose-an-option = impossible de choisir une option dans { $element }
cards-browser-card-hovered = survol de { $element }
cards-browser-card-could-not-hover = survol impossible de { $element }
cards-browser-card-failed = { $bare } — échec
cards-entities-card-listed-entities-document = entités listées · { $count } document{ $if_count_1_else_s }
chat-tool-cards-read-more-part-of = read_more · partie { $part } de { $name } #{ $seq }
cards-result-cards-documents = {" "}· { $value } documents
cards-result-cards-forms = { $tool_name } · { $forms } variantes
cards-result-cards-in = {" "}dans { $collections }
cards-result-cards-page = {" "}· page { $value }
cards-result-cards-cite-documents-documents-quotes-not = cite_documents · { $citations_len } documents · { $missing } extraits introuvables
cards-result-cards-version-unchanged = { $tool_name } · version { $version } · inchangée
cards-result-cards-version = { $tool_name } · version { $version }
web-search-card-results-in-after-deduplication = { $json_u64_doc_total_before_dedupe } résultats en entrée, { $json_u64_doc_total_after_dedupe } après dédoublonnage

board-status-on = Activé

board-status-off = Désactivé

chat-transcript-generic-tool = l’outil
