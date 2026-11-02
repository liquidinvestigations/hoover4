# Translation of en/chat.ftl. Change it together with the English catalog.

chat-activity-the-bot-is-working = Le bot travaille…
chat-composer-ask-the-bot = Demander au bot…
chat-composer-internet-tools = Outils Internet
chat-composer-agent-language-title = L'agent répond dans la langue { $language }. Modifiez la langue dans les paramètres, dans un nouvel onglet.
chat-composer-try-again-in-s = Réessayer dans { $secs } s
chat-composer-stop-the-answer-the-partial = Arrêter la réponse (la réponse partielle n'est pas enregistrée dans la discussion)
chat-composer-starting-the-conversation-u = Démarrage de la discussion…
chat-composer-send = Envoyer
chat-conversation-find-search-in-conversation = Rechercher dans la discussion
chat-conversation-find-previous-match = Correspondance précédente
chat-conversation-find-next-match = Correspondance suivante
chat-conversation-find-investigation-board = Tableau de bord d'investigation
doc-ref-card-not-openable = Non ouvrable : { $reason }.
doc-ref-card-the-search-term-was = Le terme de recherche a été{ " " }
doc-ref-card-open = Ouvrir
doc-ref-card-not-openable-2 = Non ouvrable
chat-markdown-text-show-the-cited-source = Afficher la source citée
chat-markdown-text-no-citation-of-this-conversation = Aucune citation de cette discussion n'attribue ce sigle à aucun document, donc il ne correspond à aucun.
chat-markdown-text-citations-of-this-conversation-gave = Des citations de cette discussion attribuent ce sigle à plus d'un document, donc il ne renvoie vers aucun d'entre eux.
cards-browser-card-open-the-archived-page = Ouvrir la page archivée
cards-browser-card-the-page-itself-was-not = La page elle-même n'a pas été archivée (statut : { $artifact_status }). La capture d'écran ci-dessus est ce qui a été conservé.
cards-browser-card-click-the-screenshot-to-open = Cliquer sur la capture d'écran pour ouvrir la page archivée.
cards-browser-card-show-less = Afficher moins
cards-browser-card-show-all = Tout afficher
cards-browser-card-archived-page = Page archivée
cards-browser-card-download = Télécharger
cards-browser-card-archived-copy-of = Copie archivée de { $artifact_url }
cards-browser-card-this-page-was-not-archived = Cette page n'a pas été archivée (statut : { $artifact_status }).
cards-entities-card-with-a-card = { $openable } avec une carte
cards-entities-card-the-entity-list-was-cut = La liste des entités a été coupée.
cards-entities-card-open-the-card-for-this = Ouvrir la carte pour cette valeur ({ $rule_id })
cards-entities-card-no-card-this-conversation-never = Aucune carte : cette discussion n'a jamais nommé le jeu de données d'où viennent ces valeurs, et le spectateur est adressé par jeu de données.
cards-entities-card-more-all-of-them-in = { $rest } de plus, tous dans le panneau des entités du document.
cards-entities-card-names-organisations-and-places-above = Les noms, organisations et lieux ci-dessus sont une interprétation du texte par un modèle. Aucune règle ne les a validés, il n'y a donc rien à expliquer et ils n'ouvrent rien.
cards-entities-card-nothing-extracted-from-this-document = Rien d'extrait de ce document.
chat-tool-cards-hide = Masquer
chat-tool-cards-expand = Déployer
chat-tool-cards-hide-raw-json = Masquer le JSON brut
chat-tool-cards-show-raw-json = Afficher le JSON brut
cards-result-cards-search-this = Rechercher ceci
cards-result-cards-search-every-collection = Rechercher dans toutes les collections
cards-result-cards-form = Formulaire { $index } : { $form }
cards-result-cards-show-full-text = Afficher le texte complet
cards-result-cards-quote = Citation : { $quote }
cards-result-cards-reason = Raison : { $why }
cards-result-cards-open-question = Question ouverte : { $question }
cards-result-cards-the-explore-gave-this-answer =
    L'exploration a donné cette réponse à son tableau de bord comme découverte { $kind ->
        [sourced] issue d'une source
        [inferred] déduite
        [not_found] introuvable
       *[other] de type inconnu
    }.
cards-result-cards-it-left-no-open-question = Elle n'a laissé aucune question ouverte.
cards-result-cards-open-questions-for-the-board = Questions ouvertes pour le tableau de bord :
cards-result-cards-arguments = Arguments
cards-result-cards-list-after-the-call = Liste après l'appel : { $snapshot_goal }
cards-result-cards-replaces = · remplace { $replaces_id }
cards-result-cards-the-list-at-this-version = La liste à cette version n'est pas stockée.
web-search-card-these-sources-returned-nothing-so = Ces sources n'ont rien retourné, donc les résultats proviennent d'un nombre inférieur à celui prévu
web-search-card-u-degraded = ⚠ { $degraded_len } dégradé
web-search-card-form = Formulaire { $index } : { $form }
web-search-card-no-results-from = Aucun résultat de : { $degraded_text }
web-search-card-no-results-every-source-answered = Aucun résultat. Chaque source a répondu et aucune n'avait quelque chose pour cette requête.
web-search-card-the-lowest-ranked-results-were = Les résultats les moins bien classés ont été supprimés pour que cet appel tienne dans la transcription. L'assistant les a tous vus.
web-search-card-view-search-details = Voir les détails de la recherche.
web-search-card-the-stored-result-could-not = le résultat stocké n'a pas pu être lu en tant que JSON
web-search-card-nothing-was-stored-for-this = Rien n'a été enregistré pour cet appel.
web-search-card-forms = Formulaires : { $forms }
web-search-card-kind = Type : { $row_kind }
web-search-card-published = Publié : { $row_published }
web-search-card-loading-search-detail-u = Chargement des détails de la recherche…
web-search-card-could-not-load-the-search = Impossible de charger les détails de la recherche : { $e }
web-search-card-malformed-detail = Détails mal formés : { $e }
web-search-card-the-tool-returned-selected-results = L'outil a retourné des résultats sélectionnés au modèle.
web-search-card-results-use-reciprocal-rank-fusion = Les résultats utilisent la fusion des rangs réciproques.
web-search-card-returned-nothing = n'a retourné rien : { $degraded }
web-search-card-all-candidates-use-fusion-order = Tous les candidats utilisent l'ordre de fusion.
web-search-card-the-cross-encoder-ranks-selected = Le cross-encodeur classe les résultats sélectionnés.
web-search-card-selected-results-use-fusion-order = Les résultats sélectionnés utilisent l'ordre de fusion.
web-search-card-search-detail = Détails de la recherche
web-search-card-rrf = RRF #{ $row_rrf_rank }
chat-tool-disclosure-search-this = Rechercher ceci
chat-tool-disclosure-search-every-collection = Rechercher dans toutes les collections
chat-tool-disclosure-hide = Masquer
chat-tool-disclosure-expand = Déployer
chat-tool-disclosure-this-step-was-recorded-before = Cette étape a été enregistrée avant l'enregistrement des arguments de l'outil et de ses résultats. Seule la synthèse ci-dessous est disponible.
chat-tool-disclosure-arguments = Arguments
chat-tool-disclosure-result = Résultat
chat-tool-disclosure-hide-raw-json = Masquer le JSON brut
chat-tool-disclosure-show-raw-json = Afficher le JSON brut
chat-tool-disclosure-input-json = JSON d'entrée
chat-tool-disclosure-output-json = JSON de sortie
chat-transcript-ask-a-question-about-the = Posez une question sur les documents de vos collections.
chat-transcript-suggested-next = Prochaine suggestion…
chat-transcript-earlier-answer = Réponse précédente
chat-transcript-tokens-the-conversation-carries-the = Jetons que la conversation prend en charge, plus le plus grand contexte unique facturé pour ce tour, et la part de la fenêtre du modèle utilisée
chat-transcript-instruction-to-the-agent = Instruction à l'agent
chat-transcript-the-context-stays-above-the = Le contexte reste au-dessus de la cible de { $target }.
chat-transcript-summary-parts-failed-the-record = { $failed } parties du résumé ont échoué. L'enregistrement ne contient que les listes.
chat-transcript-show-the-record = Afficher l'enregistrement
chat-transcript-hide-reasoning = Masquer le raisonnement
chat-transcript-show-reasoning = Afficher le raisonnement
chat-transcript-from-u-hide = { $count } { $noun } de { $tool } — masquer
chat-transcript-from-u-show = { $count } { $noun } de { $tool } — afficher
chat-transcript-u-hide = { $summary } — masquer
chat-transcript-u-show = { $summary } — afficher
chat-transcript-citations-of-this-conversation-give = Les citations de cette conversation donnent { $doc_handle } à plus d'un document. La réponse ne le relie à aucun d'eux.
chat-transcript-report = Signaler { $label }
chat-transcript-open-in-the-workspace = Ouvrir dans l'espace de travail
chat-transcript-this-version-could-not-be = Cette version n'a pas pu être lue. Le texte de la discussion de la réponse suit.
chat-transcript-files = Fichiers
chat-transcript-version = { $file_name }, version { $file_version }
chat-web-find-exact-text = Trouver le texte exact
chat-web-previous-match = Correspondance précédente
chat-web-next-match = Correspondance suivante
chat-web-close-preview = Fermer l'aperçu
chat-web-the-captured-page-could-not = La page capturée n'a pas pu être chargée.
chat-web-loading = Chargement…
chat-workspace-pane-workspace = Espace de travail
chat-workspace-pane-close-the-workspace = Fermer l'espace de travail
chat-workspace-pane-close = Fermer
chat-workspace-pane-loading-the-files-u = Chargement des fichiers…
chat-workspace-pane-the-files-could-not-be = Les fichiers n'ont pas pu être chargés : { $error }
chat-workspace-pane-this-conversation-has-no-files = Cette conversation n'a pas de fichiers.
chat-workspace-pane-version = version { $entry_version }, { $length_text_entry_chars }
chat-workspace-pane-choose-a-file-to-read = Choisissez un fichier pour le lire.
chat-workspace-pane-loading-the-file-u = Chargement du fichier…
chat-workspace-pane-the-file-could-not-be = Le fichier n'a pas pu être chargé : { $error }
chat-workspace-pane-version-2 = { $found_name }, version { $found_version }
chat-board-create-collections = Collections
chat-board-create-loading-collections-u = Chargement des collections…
chat-board-create-hoover-search-new-board = Recherche Hoover - Nouveau tableau
chat-board-create-ai-chat = Discussion IA
chat-board-create-new-investigation-board = Nouveau tableau d'enquête
chat-board-create-a-board-runs-its-goals = Un tableau exécute ses objectifs sous forme de séquence d'explorations d'agent. Chaque exploration est une discussion qui se termine par une seule découverte du tableau. Vous examinez la réponse de chaque objectif, et vous pouvez rejeter des découvertes et ajouter des indications pendant l'exécution.
chat-board-create-title = Titre
chat-board-create-goal = Objectif
chat-board-create-remove-this-goal = Supprimer cet objectif
chat-board-create-remove = Supprimer
chat-board-create-add-a-goal = Ajouter un objectif
chat-board-create-context-optional = Contexte (facultatif)
chat-board-create-hints-one-per-line-optional = Indications, une par ligne (facultatif)
chat-board-create-sources = Sources
chat-board-create-internet-tools = Outils Internet
chat-board-create-creating-board = Création du tableau...
chat-board-create-create-board = Créer le tableau
ai-chat-board-hoover-search-board = Hoover Search - Tableau
ai-chat-board-loading-the-board-u = Chargement du tableau…
ai-chat-board-show-the-board-overview = Afficher la vue d'ensemble du tableau
ai-chat-board-zoom-out = Réduire
ai-chat-board-zoom-in = Agrandir
ai-chat-board-u-ai-chat = ← Discussion IA
ai-chat-board-settings = Paramètres
ai-chat-board-board-settings = Paramètres du tableau
ai-chat-board-internet-tools = Outils Internet
ai-chat-board-the-next-explores-of-the = Les explorations suivantes du tableau peuvent rechercher sur le web et lire des pages web. Les explorations en cours conservent le设定 qu'elles ont adopté au départ.
ai-chat-board-collections = Collections
ai-chat-board-the-collections-are-fixed-when = Les collections sont fixées lors de la création du tableau.
ai-chat-board-confirm-drop = Confirmer le dépôt
ai-chat-board-drop-the-board = Déposer le tableau
ai-chat-board-close = Fermer
ai-chat-board-the-board-used-its-explore = Le tableau a utilisé sa limite d'exploration
ai-chat-board-the-board-used-explores-the = Le tableau a utilisé { $explore_limit } explorations, la limite d'un tableau. Il ne démarre plus de travail. Vous pouvez encore décider des réponses proposées.
ai-chat-board-create-a-new-board-to = Créer un nouveau tableau pour continuer l'enquête
ai-chat-board-goal = Objectif
ai-chat-board-goals = Objectifs
ai-chat-board-add-new-goal = Ajouter un nouvel objectif...
ai-chat-board-a-new-goal = Un nouvel objectif
ai-chat-board-add-goal = Ajouter un objectif
ai-chat-board-a-board-has-at-most = Un tableau a au plus { $max_goals } objectifs. Créez un nouveau tableau pour un autre objectif.
ai-chat-board-background-context = Contexte de départ
ai-chat-board-continue-with-a-correction = Continuer avec une correction
ai-chat-board-correction-what-is-wrong-or = Correction : ce qui est incorrect ou manquant. Le tableau continue avec.
ai-chat-board-the-board-waits-for-your = Le tableau attend votre examen
ai-chat-board-the-board-used-its-budget = Le tableau a utilisé son budget de { $snap_max_explores } explorations.
ai-chat-board-the-assessments-gave-no-usable = Les évaluations n'ont donné aucune direction exploitable.
ai-chat-board-accept-or-reject-the-proposed = Acceptez ou rejetez la réponse proposée de chaque objectif ci-dessus. Une réponse rejetée permet au tableau de continuer immédiatement.
ai-chat-board-no-proposed-answer-waits-for = Aucune réponse proposée n'attend votre décision.
ai-chat-board-reopen-the-board-to-continue = Rouvrir le tableau pour continuer les objectifs ouverts. Il conserve ses découvertes et ses réponses.
ai-chat-board-close-the-board-to-accept = Fermer le tableau pour accepter toutes les réponses proposées et l'arrêter, ou le continuer avec une correction.
ai-chat-board-close-the-board = Fermer le tableau
ai-chat-board-or-reopen-the-board-to = Ou rouvrir le tableau pour continuer les objectifs ouverts sans correction.
ai-chat-board-the-board-is-complete = Le tableau est complet
ai-chat-board-a-goal-has-no-accepted = Un objectif n'a pas de réponse acceptée. Rouvrez le tableau pour le continuer. Le tableau conserve ses découvertes et ses réponses.
ai-chat-board-add-a-hint = Ajouter un indice
ai-chat-board-the-next-assessment-reads-every = L'évaluation suivante lit chaque indice. Un indice répond aussi à une exploration qui posait une question.
ai-chat-board-add-hint = Ajouter un commentaire
ai-chat-board-events = Événements
ai-chat-board-newest-first = Plus récents en premier
ai-chat-board-date = Date
ai-chat-board-actor = Auteur
ai-chat-board-event = Événement
ai-chat-board-show-details = Afficher les détails
ai-chat-board-open = Ouvrir
ai-chat-board-show-the-newest-events = Afficher les { $event_rows } événements les plus récents
ai-chat-board-show-all-events = Afficher tous les { $snap_events_len } événements
ai-chat-board-statistics = Statistiques
ai-chat-board-explores = Explorer
ai-chat-board-model-steps-per-explore = Étapes du modèle par exploration
ai-chat-board-assessments = Évaluations
ai-chat-board-intents = Intentions
ai-chat-board-findings = Découvertes
ai-chat-board-created = Créé
ai-chat-board-rejected-this-finding-on-the = { $rejected_by } a rejeté cette découverte le { $format_utc_ms_fact_rejected_ms }. Le tableau n'utilise plus cette découverte.
ai-chat-board-rejected-this-finding-the-board = { $rejected_by } a rejeté cette découverte. Le tableau n'utilise plus cette découverte.
ai-chat-board-no-reason-was-given = Aucune raison n'a été indiquée.
ai-chat-board-reason = Raison : { $fact_rejected_reason }
ai-chat-board-open-questions = Questions ouvertes
ai-chat-board-explored-in = Explorée dans
ai-chat-board-explore-this-question = Explorer cette question
ai-chat-board-your-questions = Vos questions
ai-chat-board-ask-about-the-background-context = Demander des informations sur le contexte
ai-chat-board-ask-about-this-finding = Demander des informations sur cette découverte
ai-chat-board-a-follow-up-question-about = Question de suivi sur ce nœud
ai-chat-board-ask = Demander
ai-chat-board-checks-that-changed-this-finding = Contrôles ayant modifié cette découverte
ai-chat-board-reject-this-correction = Rejeter cette correction
ai-chat-board-reject-this-finding = Rejeter cette découverte
ai-chat-board-not-answered-the-board-was = Pas de réponse. Le tableau de bord a été terminé sans réponse à cet objectif. Une indication ou une réouverture l'ouvre à nouveau.
ai-chat-board-no-answer-yet = Pas encore de réponse.
ai-chat-board-the-findings-of-this-answer = Les découvertes de cette réponse sont des recherches qui n'ont rien trouvé. Acceptez pour consigner que les documents ne répondent pas à l'objectif, ou rejetez pour poursuivre l'enquête.
ai-chat-board-open-an-assessment-to-read = { "." } Ouvrez une évaluation pour lire pourquoi.
ai-chat-board-from-the-findings = À partir des découvertes{ " " }
ai-chat-board-accept-answer = Accepter la réponse
ai-chat-board-why-the-answer-is-wrong = Pourquoi la réponse est incorrecte ou incomplète
ai-chat-board-reject-answer = Rejeter la réponse
ai-chat-board-intent = Objectif
ai-chat-board-attempts-declared = Tentatives : { $intent_attempts }. Déclaré { $format_utc_ms_intent_created_ms }.
ai-chat-board-the-explore-asked = L'exploration a demandé
ai-chat-board-add-a-hint-in-the = Ajoutez une indication dans l'aperçu du tableau de bord pour y répondre.
ai-chat-board-last-error = Dernière erreur
ai-chat-board-brief = Brief
ai-chat-board-open-the-explore-chat = Ouvrir la discussion d'exploration
ai-chat-board-loading-the-assessment-u = Chargement de l'évaluation…
ai-chat-board-assessment = Évaluation { $reason_no }
ai-chat-board-model-outcome-ms = { $format_utc_ms_a_created_ms }. Modèle { $a_model }. Résultat { $a_outcome }. { $a_latency_ms } ms, { $tokens }.
ai-chat-board-checks-that-changed-it = Vérifications qui l'ont modifié
ai-chat-board-prompt = Prompt
ai-chat-board-this-assessment-ran-before-the = Cette évaluation a été exécutée avant que les prompts ne soient stockés.
ai-chat-board-response = Réponse
ai-chat-history-hoover-search-chat-history = Recherche Hoover - Historique des discussions
ai-chat-history-u-back = ← Retour
ai-chat-history-conversation-history = Historique de la conversation
ai-chat-history-show-board-chats = Afficher les discussions du tableau de bord
ai-chat-history-loading-u = Chargement…
ai-chat-history-could-not-load-history = Impossible de charger l'historique : { $e }
ai-chat-history-no-conversations-yet = Aucune discussion pour l'instant.
ai-chat-history-board = Tableau de bord
ai-chat-history-new-chat = Nouvelle discussion
ai-chat-history-messages-updated = { $s_message_count } messages · mis à jour le { $s_updated_at }
ai-chat-history-delete-conversation = Supprimer la discussion
ai-chat-history-delete = Supprimer
ai-chat-homepage-hoover-search-ai-chat = Recherche Hoover - Discussion IA
ai-chat-homepage-what-are-you-researching = Que recherchez-vous ?
ai-chat-homepage-view-all-conversations = Voir toutes les discussions
ai-chat-homepage-starting-conversation-u = Démarrage de la discussion…
ai-chat-homepage-investigation-boards = Tableaux de bord d'enquête
ai-chat-homepage-new-board = Nouveau tableau de bord
ai-chat-homepage-loading-boards-u = Chargement des tableaux de bord…
ai-chat-homepage-could-not-load-the-boards = Impossible de charger les tableaux de bord : { $user_facing_message_e }
ai-chat-homepage-you-have-no-board-a = Vous n'avez aucun tableau de bord. Un tableau de bord mène une longue enquête sous forme d'une série d'explorations par l'agent, et vous en passez les réponses en revue.
ai-chat-homepage-updated = Mis à jour le { $format_utc_ms_board_updated_ms }
ai-chat-session-hoover-search-ai-chat = Recherche Hoover - Discussion IA
ai-chat-session-this-conversation-could-not-be = Cette discussion n'a pas pu être chargée.
ai-chat-session-loading-u = Chargement…
ai-chat-session-u-chats = ← Discussions
ai-chat-session-history = Historique
ai-chat-session-show-the-files-that-the = Afficher les fichiers que l'assistant a écrits dans cette discussion
ai-chat-session-workspace = Espace de travail
ai-chat-session-this-answer-was-interrupted-before = Cette réponse a été interrompue avant sa complétion, car la page ou le serveur s'est arrêté en cours de tour. Demandez à nouveau pour réessayer.
ai-chat-session-dismiss = Ignorer
ai-chat-session-board-explore-chats-are-read = Les discussions d'exploration du tableau de bord sont en lecture seule.{ " " }
ai-chat-session-open-the-board = Ouvrir le tableau de bord
chat-locked-options-on = { $label } : activé
chat-locked-options-off = { $label } : désactivé
chat-tool-cards-running-u = en cours…
cards-result-cards-quote-found = Citation trouvée
cards-result-cards-quote-not-found = Citation non trouvée
cards-result-cards-quote-not-checked = Citation non vérifiée
web-search-card-results = { $results_len } résultats
chat-tool-disclosure-running-u = en cours…
chat-transcript-call = appel
chat-transcript-calls = appels
ai-chat-board-a-board-without-collections-needs = Un tableau sans collection nécessite des outils Internet.
ai-chat-board-of = { $snap_explores_used } sur { $snap_max_explores }
ai-chat-board-assessment-2 = évaluation { $number }
ai-chat-history-messages = { $s_message_count } messages
web-search-card-reranked-in = Le cross-encoder a réordonné les résultats en { $ms } ms.
web-search-card-engine-results = { $name } : { $count } en { $ms } ms
web-search-card-score-was-rank = score { $score } · classé RRF n° { $rank }
chat-activity-the-turn-waits-for-a = Le tour attend une place de modèle libre.
chat-activity-the-turn-waits-for-a-2 = Le tour attend une place d'outil libre.
chat-locked-options-start-a-new-chat-to = Démarrer une nouvelle discussion pour modifier ce paramètre.
chat-locked-options-internet-tools = Outils Internet
chat-session-card-new-chat = Nouvelle discussion
chat-tool-cards-first-frame-of-the-video = Première image de la vidéo
chat-tool-cards-screenshot-of = Capture d'écran de
chat-tool-cards-image = Image
cards-result-cards-the-agent-asked-a-question = L'agent a posé une question.
chat-transcript-hide = Masquer
chat-transcript-show = Afficher
chat-transcript-unverified-quote-the-quoted-span = Citation non vérifiée. Le span cité est trop court pour être vérifié.
chat-transcript-unverified-quote-the-document-text = Citation non vérifiée. Le texte du document n'a pas pu être lu.
chat-transcript-unverified-quote-this-wording-was = Citation non vérifiée. Cette formulation n'a pas été trouvée dans le document.
chat-board-create-select-a-collection-or-turn = Sélectionnez une collection ou activez les outils Internet.
chat-board-create-select-at-least-one-collection = Sélectionnez au moins une collection.
ai-chat-board-active = Actif
ai-chat-board-paused = En pause
ai-chat-board-waits-for-review = En attente de révision
ai-chat-board-completed = Terminé
ai-chat-board-dropped = Abandonné
ai-chat-board-unknown = Inconnu
ai-chat-board-pause-the-board = Mettre le tableau en pause
ai-chat-board-resume-the-board = Reprendre le tableau
ai-chat-board-none = Aucun
ai-chat-board-reopen-with-the-remaining-budget = Rouvrir avec le budget restant
ai-chat-board-finding = Découverte
ai-chat-board-why-the-correction-is-wrong = Pourquoi la correction est erronée
ai-chat-board-reject-correction = Rejeter la correction
ai-chat-board-why-the-finding-is-wrong = Pourquoi la découverte est erronée
ai-chat-board-reject-finding = Rejeter la découverte
ai-chat-board-answer = Réponse
ai-chat-board-proposed-answer = Réponse proposée
ai-chat-homepage-active = Actif
ai-chat-homepage-paused = En pause
ai-chat-homepage-waits-for-review = En attente de révision
ai-chat-homepage-completed = Terminé
ai-chat-homepage-dropped = Abandonné
ai-chat-homepage-unknown = Inconnu
cards-result-cards-submitted-by-board =
    Soumis par le tableau : { $kind ->
        [sourced] une source
        [inferred] une inférence
        [not_found] une non trouvaille
       *[other] un type inconnu
    } découverte du rapport
cards-result-cards-finding-for-board =
    { $kind ->
        [sourced] Une source
        [inferred] Une inférence
        [not_found] Une non trouvaille
       *[other] Un type inconnu
    } découverte pour le tableau
chat-transcript-compacting = Compactage du contexte : { $before } jetons vers une cible de { $target }.
chat-transcript-compaction-failed = Le résumé des étapes antérieures a échoué. Le modèle a reçu les étapes antérieures inchangées, { $after } jetons.
chat-transcript-compacted = Contexte compacté : { $steps } étapes résumées, { $before } jetons vers { $after }.
ai-chat-board-reopen-with-more = Rouvrir avec { $grant } explorations supplémentaires
ai-chat-board-goal-number = Objectif { $number }
ai-chat-board-from-assessment-on = À partir de l'évaluation { $number } le { $date }.
ai-chat-board-from-assessment = À partir de l'évaluation { $number }.
chat-board-create-goal-2 = Objectif { $index_1 }
ai-chat-session-lost-contact-with-the-chat = a perdu le contact avec la discussion : { $e }
ai-chat-session-could-not-stop-the-answer = impossible d’arrêter la réponse : { $e } — elle est toujours en cours d’exécution
ai-chat-board-later-assessments-dropped-an-answer = { $n } évaluations suivantes ont abandonné une réponse pour cet objectif :
ai-chat-board-prompt-and-completion-tokens = { $a_prompt_tokens } tokens de consigne et { $a_completion_tokens } tokens de complétion
ai-chat-homepage-completed-goals-not-answered = Terminés, { $n } objectifs sans réponse
board-graph-intent = intention, { $state }
chat-workspace-pane-characters = { $chars } caractères
chat-transcript-running-tool = { $tool_run_summary_messages_start_end_run_ } + { $joined_live_end } outil en cours d'exécution { $if_joined_live_end_1_tr_chat_transcript_ }
chat-transcript-running-tool-2 = { $turn_tool_rows_len } outil en cours d'exécution { $if_turn_tool_rows_len_1_tr_chat_transcri }
chat-transcript-answered-after-failed-attempt = Répondu après { $retries_len } tentative{ $if_retries_len_1_else_s } échouée
chat-transcript-failed-attempt = { $retries_len } tentative{ $if_retries_len_1_else_s } échouée
chat-transcript-version-2 = { $report_name }, version { $report_version }
tool-run-summary-searched =
    { $n ->
        [one] a recherché { $n } terme
       *[other] a recherché { $n } termes
    }
tool-run-summary-read =
    { $n ->
        [one] a lu { $n } document
       *[other] a lu { $n } documents
    }
tool-run-summary-searched-the-web-for =
    { $n ->
        [one] a recherché sur le web { $n } terme
       *[other] a recherché sur le web { $n } termes
    }
tool-run-summary-read-web =
    { $n ->
        [one] a lu { $n } page web
       *[other] a lu { $n } pages web
    }
tool-run-summary-browser =
    { $n ->
        [one] { $n } action de navigateur
       *[other] { $n } actions de navigateur
    }
tool-run-summary-listed-the-entities-of =
    { $n ->
        [one] a listé les entités de { $n } document
       *[other] a listé les entités de { $n } documents
    }
tool-run-summary-cited =
    { $n ->
        [one] a cité { $n } document
       *[other] a cité { $n } documents
    }
tool-run-summary-cited-web =
    { $n ->
        [one] a cité { $n } page web
       *[other] a cité { $n } pages web
    }
tool-run-summary-read-and-tool-texts =
    { $n ->
        [one] a lu { $n } texte de compétence et d'outil
       *[other] a lu { $n } textes de compétence et d'outil
    }
tool-run-summary-saved =
    { $n ->
        [one] a enregistré { $n } note
       *[other] a enregistré { $n } notes
    }
tool-run-summary-todo-list =
    { $n ->
        [one] { $n } appel à la liste de tâches
       *[other] { $n } appels à la liste de tâches
    }
tool-run-summary-to-the-agent =
    { $n ->
        [one] { $n } instruction à l'agent
       *[other] { $n } instructions à l'agent
    }
tool-run-summary-other =
    { $n ->
        [one] { $n } autre appel
       *[other] { $n } autres appels
    }
tool-run-summary-failed = { $failures } échoué
tool-run-summary-took = a pris { $duration_text_ms }
chat-session-card-messages = { $session_message_count } message
chat-tool-disclosure-item =
    { $count ->
        [one] { $count } élément
       *[other] { $count } éléments
    }
chat-tool-disclosure-field =
    { $count ->
        [one] { $count } champ
       *[other] { $count } champs
    }
chat-tool-disclosure-searched-collections = collections recherchées{ $filters }
chat-tool-disclosure-searched-collections-2 = collections recherchées · { $query }{ $filters }
chat-tool-disclosure-cited-documents = { $n } document cité
chat-tool-disclosure-read-document = document lu · { $path }
chat-tool-disclosure-searched-the-web = web recherué · { $q }
chat-tool-disclosure-opened-page = page ouverte · { $u }
chat-tool-disclosure-whois = whois · { $d }
chat-tool-disclosure-called = appelé { $other }
chat-tool-disclosure-called-2 = appelé { $other } · { $short }
cards-browser-card-opened = { $url } ouvert
cards-browser-card-could-not-open = impossible d'ouvrir { $url }
cards-browser-card-clicked = clic sur { $element }
cards-browser-card-could-not-click = impossible de cliquer sur { $element }
cards-browser-card-typed-into = saisie dans { $element }
cards-browser-card-could-not-type-into = impossible de saisir dans { $element }
cards-browser-card-typed = « { $text } » saisi
cards-browser-card-could-not-type = impossible de saisir « { $text } »
cards-browser-card-pressed = touche { $key } pressée
cards-browser-card-could-not-press = impossible de presser la touche { $key }
cards-browser-card-chose-an-option-in = option choisie dans { $element }
cards-browser-card-could-not-choose-an-option = impossible de choisir une option dans { $element }
cards-browser-card-hovered = survol de { $element }
cards-browser-card-could-not-hover = impossible de survoler { $element }
cards-browser-card-failed = { $bare } — échec
cards-entities-card-listed-entities-document = entités répertoriées · { $count } document{ $if_count_1_else_s }
chat-tool-cards-read-more-part-of = read_more · partie { $part } de { $name } #{ $seq }
cards-result-cards-documents = { " " }· { $value } document
cards-result-cards-forms = { $tool_name } · { $forms } formulaires
cards-result-cards-in = { " " }dans { $collections }
cards-result-cards-page = { " " }· page { $value }
cards-result-cards-cite-documents-documents-quotes-not = cite_documents · { $citations_len } documents · { $missing } citations introuvables
cards-result-cards-version-unchanged = { $tool_name } · version { $version } · inchangée
cards-result-cards-version = { $tool_name } · version { $version }
web-search-card-results-in-after-deduplication = { $json_u64_doc_total_before_dedupe } résultats, { $json_u64_doc_total_after_dedupe } après dédoublonnage
