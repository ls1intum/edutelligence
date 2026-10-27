package de.tum.cit.aet.logos.logoswebservice.configuration.service;

import java.util.Comparator;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import java.util.regex.Pattern;

import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.transaction.support.TransactionTemplate;

import de.tum.cit.aet.logos.logoswebservice.configuration.HfReachabilityUnavailableException;
import de.tum.cit.aet.logos.logoswebservice.configuration.ModelAlreadyAvailableException;
import de.tum.cit.aet.logos.logoswebservice.configuration.ModelNotOnHuggingFaceException;
import de.tum.cit.aet.logos.logoswebservice.configuration.dto.RequestedModelResponse;
import de.tum.cit.aet.logos.logoswebservice.configuration.entity.RequestedModel;
import de.tum.cit.aet.logos.logoswebservice.configuration.entity.RequestedModelVote;
import de.tum.cit.aet.logos.logoswebservice.configuration.repository.ModelAliasRepository;
import de.tum.cit.aet.logos.logoswebservice.configuration.repository.ModelRepository;
import de.tum.cit.aet.logos.logoswebservice.configuration.repository.RequestedModelRepository;
import de.tum.cit.aet.logos.logoswebservice.configuration.repository.RequestedModelVoteRepository;
import de.tum.cit.aet.logos.logoswebservice.identity.repository.TeamMemberRepository;
import de.tum.cit.aet.logos.logoswebservice.orchestrator.OrchestratorHfReachabilityClient;
import de.tum.cit.aet.logos.logoswebservice.orchestrator.OrchestratorHfReachabilityClient.HfReachabilityResult;

/**
 * The model-request voting feature: record demand for models Logos does not
 * serve yet, and show what everyone has asked for.
 *
 * This is a demand signal, not a configuration change — nothing here provisions
 * a model. Each user gets one vote per requested model; they can take the vote
 * back and cast it again. A name an admin later adds to {@code models} or to a
 * model's aliases is no longer "requested": voting for it is refused and it
 * drops out of the listing.
 *
 * Names are Hugging Face-style {@code provider/model} identifiers (e.g.
 * {@code openai/gpt-oss-120b}); a leading {@code https://huggingface.co/} URL
 * prefix is accepted and stripped, so a model is always stored under its
 * plain name.
 *
 * A submission is only recorded when the name passes the Hugging Face
 * precheck (via the orchestrator): the repository must be reachable for the
 * central HF_TOKEN, or gated — a gated repository can be pulled once an admin
 * accepts its license, so it is a legitimate request, flagged with
 * {@code is_gated = true}. The row carries the gating verdict in
 * {@code is_gated} (true when the Hub rejects the repository as gated, false
 * when it is reachable); a repository the Hub does not know at all is
 * refused. Rows that predate the precheck are backfilled by
 * {@link RequestedModelHfStatusSweeper} at application start.
 *
 * Every vote names the team the model is wanted for; the first team to ask is
 * recorded on the row ({@code first_requesting_team}) and never overwritten —
 * later votes from other teams count toward the total, they just do not
 * change who requested first. That team's app admin is the one who accepts a
 * gated model's license agreement.
 */
@Service
public class RequestedModelService {

    /**
     * Arbitrary stable key identifying the requested-model name namespace to
     * {@code pg_advisory_xact_lock}; the value itself is meaningless.
     */
    private static final long REQUESTED_MODELS_NAMESPACE_LOCK_KEY = 0x5245514D4F444C53L; // "REQMODLS"

    /**
     * Maximum length of a requested-model name.
     *
     * The name column is {@code TEXT}, so nothing there rejects a long name —
     * but the registry's unique index {@code uq_requested_models_name_lower}
     * is a b-tree over {@code lower(name)}, and PostgreSQL refuses to store
     * index entries larger than 2704 bytes (half a default 8 kB page). An
     * unbounded name would therefore not fail a column check but blow up at
     * insert time with a raw database error. 255 characters stay far below
     * that even for multi-byte scripts, and are well past any real model name.
     */
    private static final int MAX_NAME_LENGTH = 255;

    /** Hugging Face URL prefix accepted in submitted names and stripped before processing. */
    private static final String HUGGINGFACE_URL_PREFIX = "https://huggingface.co/";

    /**
     * A requestable model name: {@code provider/model} in the Hugging Face
     * identifier form — alphanumerics, dots, dashes and underscores, with
     * exactly one slash between two non-empty parts.
     */
    private static final Pattern MODEL_NAME_PATTERN =
        Pattern.compile("[A-Za-z0-9._-]+/[A-Za-z0-9._-]+");

    private final RequestedModelRepository requestedModelRepository;
    private final RequestedModelVoteRepository voteRepository;
    private final ModelRepository modelRepository;
    private final ModelAliasRepository modelAliasRepository;
    private final TeamMemberRepository teamMemberRepository;
    private final OrchestratorHfReachabilityClient hfReachabilityClient;
    private final TransactionTemplate transactionTemplate;

    public RequestedModelService(RequestedModelRepository requestedModelRepository,
                                 RequestedModelVoteRepository voteRepository,
                                 ModelRepository modelRepository,
                                 ModelAliasRepository modelAliasRepository,
                                 TeamMemberRepository teamMemberRepository,
                                 OrchestratorHfReachabilityClient hfReachabilityClient,
                                 TransactionTemplate transactionTemplate) {
        this.requestedModelRepository = requestedModelRepository;
        this.voteRepository = voteRepository;
        this.modelRepository = modelRepository;
        this.modelAliasRepository = modelAliasRepository;
        this.teamMemberRepository = teamMemberRepository;
        this.hfReachabilityClient = hfReachabilityClient;
        this.transactionTemplate = transactionTemplate;
    }

    /**
     * Every requested model that is not yet served by Logos — neither by its
     * own name nor as an alias of a served model — most-voted first (ties
     * broken by name). Each entry carries its vote count and whether the given
     * user has voted for it, so the page can render the vote/undo control.
     */
    public List<RequestedModelResponse> list(Integer userId) {
        Set<String> available = modelRepository.findAll().stream()
            .map(model -> model.getName().toLowerCase(Locale.ROOT))
            .collect(java.util.stream.Collectors.toCollection(HashSet::new));
        modelAliasRepository.findAll().stream()
            .map(alias -> alias.getAlias().toLowerCase(Locale.ROOT))
            .forEach(available::add);

        Map<Integer, Long> voteCounts = new HashMap<>();
        Set<Integer> myVotedModelIds = new HashSet<>();
        for (RequestedModelVote vote : voteRepository.findAll()) {
            voteCounts.merge(vote.getRequestedModelId(), 1L, Long::sum);
            if (userId != null && userId.equals(vote.getUserId())) {
                myVotedModelIds.add(vote.getRequestedModelId());
            }
        }

        return requestedModelRepository.findAll().stream()
            .filter(model -> !available.contains(model.getName().toLowerCase(Locale.ROOT)))
            .map(model -> new RequestedModelResponse(
                model.getId(),
                model.getName(),
                voteCounts.getOrDefault(model.getId(), 0L).intValue(),
                myVotedModelIds.contains(model.getId()),
                model.getIsGated(),
                model.getFirstRequestingTeam()))
            .sorted(Comparator
                .comparingInt(RequestedModelResponse::requestCount).reversed()
                .thenComparing(RequestedModelResponse::name, String.CASE_INSENSITIVE_ORDER))
            .toList();
    }

    /**
     * Cast the user's vote for a model.
     *
     * The name must be a Hugging Face-style {@code provider/model} identifier
     * such as {@code openai/gpt-oss-120b}; a leading
     * {@code https://huggingface.co/} URL prefix is stripped before
     * processing, so the model is stored and listed under its plain name.
     *
     * Refused when the name is already served by Logos, as a model name or an
     * alias of one (it is not something to request); that check is repeated
     * under the shared model-name/alias namespace lock before persisting, so
     * a model or alias added while the precheck was in flight is refused, too.
     * Only then is the name
     * checked against Hugging Face through the orchestrator: the vote is
     * recorded when the repository is visible to the central HF_TOKEN or
     * gated (the row is then flagged with {@code is_gated = true}), refused
     * when the Hub does not know it, and retriable when the Hub could not be
     * asked. Otherwise the model's registry row is created if needed and the
     * user's vote recorded. The unique (model, user) index means a second
     * vote by the same user is a no-op — everyone still gets exactly one
     * vote.
     *
     * The vote names the team the model is wanted for: the caller must be a
     * member of it, and the first team to ask is recorded on the row (a row
     * that already carries one keeps it, so later teams only add votes).
     *
     * @throws IllegalArgumentException when no name is given, the name is not
     *     in {@code provider/model} form, it exceeds the maximum length, no
     *     team is given, or the caller is not a member of the given team
     * @throws ModelAlreadyAvailableException when the name is already in Logos
     * @throws ModelNotOnHuggingFaceException when the Hub does not know the
     *     repository (or the central HF_TOKEN may not see it, for a reason
     *     other than gating)
     * @throws HfReachabilityUnavailableException when the precheck timed out
     *     or the orchestrator could not be reached
     */
    public RequestedModelResponse vote(Integer userId, String name, Integer teamId) {
        // Validation, the availability check and the Hugging Face precheck run
        // without a transaction: the precheck is a remote round trip (bounded
        // by the orchestrator's Hub timeout) and must not hold a pooled
        // database connection while it waits for the answer.
        if (name == null || name.isBlank()) {
            throw new IllegalArgumentException("A model name is required.");
        }
        requireUser(userId);
        String normalized = normalizeName(name);
        if (!MODEL_NAME_PATTERN.matcher(normalized).matches()) {
            throw new IllegalArgumentException(
                "The model name must be in provider/model form, e.g. 'openai/gpt-oss-120b'.");
        }
        if (normalized.length() > MAX_NAME_LENGTH) {
            throw new IllegalArgumentException(
                "The model name must be at most " + MAX_NAME_LENGTH + " characters.");
        }
        requireRequestingTeam(userId, teamId);
        if (isAlreadyAvailable(normalized)) {
            throw new ModelAlreadyAvailableException("This model is already available in Logos.");
        }
        boolean gated = requireModelOnHuggingFace(normalized);

        // Only the registry/vote persistence is transactional, so the advisory
        // locks are bound to the same transaction they protect.
        return transactionTemplate.execute(status -> {
            // The availability check above ran before the precheck, so a model
            // or alias may have been added since. Re-check under the shared
            // model-name/alias namespace lock — the same lock ModelService takes
            // for its mutations: a concurrent add either commits before we read
            // (and is rejected here) or waits for this transaction to finish.
            modelAliasRepository.lockModelAliasNamespace(
                ModelAliasRepository.MODEL_ALIAS_NAMESPACE_LOCK_KEY);
            if (isAlreadyAvailable(normalized)) {
                throw new ModelAlreadyAvailableException("This model is already available in Logos.");
            }
            requestedModelRepository.lockRequestedModelsNamespace(REQUESTED_MODELS_NAMESPACE_LOCK_KEY);
            RequestedModel model = requestedModelRepository.findByNameIgnoreCase(normalized).orElseGet(() -> {
                RequestedModel created = new RequestedModel();
                created.setName(normalized);
                return created;
            });
            // The precheck just answered: record its gating verdict with the
            // row.
            model.setIsGated(gated);
            // The first team to request the model is recorded with the row —
            // also filling in rows that predate the column. A row that
            // already carries a team keeps it: later teams add votes, they
            // do not take the slot.
            if (model.getFirstRequestingTeam() == null) {
                model.setFirstRequestingTeam(teamId);
            }
            model = requestedModelRepository.save(model);

            if (!voteRepository.existsByRequestedModelIdAndUserId(model.getId(), userId)) {
                RequestedModelVote vote = new RequestedModelVote();
                vote.setRequestedModelId(model.getId());
                vote.setUserId(userId);
                voteRepository.save(vote);
            }
            return toResponse(model, (int) voteRepository.countByRequestedModelId(model.getId()), true);
        });
    }

    /**
     * Take the user's vote back for a model.
     *
     * Idempotent: undoing a vote that is not there (unknown model, or the user
     * did not vote) is a no-op. When a model's last vote is removed, its
     * registry row goes with it, so the list never shows a model nobody wants.
     *
     * The {@code https://huggingface.co/} prefix is stripped the same way as
     * in {@link #vote}, so a vote can be undone by URL or by plain name.
     *
     * @throws IllegalArgumentException when no name is given
     */
    @Transactional
    public RequestedModelResponse undo(Integer userId, String name) {
        if (name == null || name.isBlank()) {
            throw new IllegalArgumentException("A model name is required.");
        }
        requireUser(userId);
        String normalized = normalizeName(name);

        requestedModelRepository.lockRequestedModelsNamespace(REQUESTED_MODELS_NAMESPACE_LOCK_KEY);
        RequestedModel model = requestedModelRepository.findByNameIgnoreCase(normalized).orElse(null);
        if (model == null) {
            return new RequestedModelResponse(null, normalized, 0, false, null, null);
        }
        voteRepository.findByRequestedModelIdAndUserId(model.getId(), userId)
            .ifPresent(voteRepository::delete);
        if (voteRepository.countByRequestedModelId(model.getId()) == 0) {
            requestedModelRepository.delete(model);
            return new RequestedModelResponse(
                model.getId(), model.getName(), 0, false, model.getIsGated(), model.getFirstRequestingTeam());
        }
        return toResponse(model, (int) voteRepository.countByRequestedModelId(model.getId()), false);
    }

    /**
     * The Hugging Face precheck gate for a submission. The normalized name is
     * the repository id; {@code reachable} and a decisive {@code model-gated}
     * rejection let the vote through — a gated repository can be pulled once
     * an admin accepts its license, so it is a legitimate request to flag.
     * {@code rejected} for any other reason is a verdict from the Hub,
     * {@code unknown} (Hub timeout, orchestrator unreachable) is not a
     * verdict — both refuse the vote, with a message that tells the user
     * which case they hit.
     *
     * @return true when the Hub found the repository gated, false when it is
     *     reachable
     */
    private boolean requireModelOnHuggingFace(String normalized) {
        HfReachabilityResult reachability = hfReachabilityClient.check(normalized);
        if (HfReachabilityResult.STATUS_REACHABLE.equals(reachability.status())) {
            return false;
        }
        if (HfReachabilityResult.STATUS_REJECTED.equals(reachability.status())) {
            if (HfReachabilityResult.REASON_MODEL_GATED.equals(reachability.reasonCode())) {
                return true;
            }
            throw new ModelNotOnHuggingFaceException(
                "Model not found on HuggingFace. Maybe it is a cloud model (unsupported)?");
        }
        throw new HfReachabilityUnavailableException(
            "Hugging Face did not respond in time. Please try again later.");
    }

    private RequestedModelResponse toResponse(RequestedModel model, int count, boolean hasVoted) {
        return new RequestedModelResponse(
            model.getId(), model.getName(), count, hasVoted, model.getIsGated(), model.getFirstRequestingTeam());
    }

    /**
     * Record a decisive Hugging Face gating verdict on a registry row that has
     * none yet (the application-start sweep path). A row that already carries
     * a verdict — for instance one a concurrent vote just wrote — is left
     * untouched.
     *
     * @return the number of rows updated (0 when the row already had a verdict)
     */
    @Transactional
    public int recordGatedVerdictIfAbsent(Integer modelId, Boolean status) {
        return requestedModelRepository.setIsGatedIfNull(modelId, status);
    }

    /**
     * Whether the name is already served by Logos, either as a model name or
     * as an alias of one — in either case it is not something to request.
     */
    private boolean isAlreadyAvailable(String name) {
        return modelRepository.existsByNameIgnoreCase(name)
            || modelAliasRepository.existsByAliasIgnoreCase(name);
    }

    private void requireUser(Integer userId) {
        if (userId == null) {
            throw new IllegalArgumentException("No user context.");
        }
    }

    /**
     * The request names the team the model is wanted for (its app admin
     * later accepts a gated model's license), so the caller must be a member
     * of it — the user interface only offers their own teams; this is the
     * server-side backstop.
     */
    private void requireRequestingTeam(Integer userId, Integer teamId) {
        if (teamId == null) {
            throw new IllegalArgumentException("A requesting team is required.");
        }
        if (!teamMemberRepository.isMember(teamId, userId)) {
            throw new IllegalArgumentException(
                "You can only request a model for one of your own teams.");
        }
    }

    /**
     * Canonical form of a submitted name: surrounding whitespace stripped and
     * a leading {@code https://huggingface.co/} URL prefix removed, so a model
     * submitted by its Hugging Face URL is processed under its plain
     * {@code provider/model} name.
     */
    private String normalizeName(String name) {
        String trimmed = name.strip();
        return trimmed.startsWith(HUGGINGFACE_URL_PREFIX)
            ? trimmed.substring(HUGGINGFACE_URL_PREFIX.length())
            : trimmed;
    }
}
