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

import de.tum.cit.aet.logos.logoswebservice.configuration.dto.RequestedModelResponse;
import de.tum.cit.aet.logos.logoswebservice.configuration.entity.RequestedModel;
import de.tum.cit.aet.logos.logoswebservice.configuration.entity.RequestedModelVote;
import de.tum.cit.aet.logos.logoswebservice.configuration.repository.ModelAliasRepository;
import de.tum.cit.aet.logos.logoswebservice.configuration.repository.ModelRepository;
import de.tum.cit.aet.logos.logoswebservice.configuration.repository.RequestedModelRepository;
import de.tum.cit.aet.logos.logoswebservice.configuration.repository.RequestedModelVoteRepository;

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

    /** Raised when a vote is cast for a name that is already served by Logos, as a model name or alias. */
    public static class ModelAlreadyAvailableException extends RuntimeException {
        public ModelAlreadyAvailableException(String message) {
            super(message);
        }
    }

    private final RequestedModelRepository requestedModelRepository;
    private final RequestedModelVoteRepository voteRepository;
    private final ModelRepository modelRepository;
    private final ModelAliasRepository modelAliasRepository;

    public RequestedModelService(RequestedModelRepository requestedModelRepository,
                                 RequestedModelVoteRepository voteRepository,
                                 ModelRepository modelRepository,
                                 ModelAliasRepository modelAliasRepository) {
        this.requestedModelRepository = requestedModelRepository;
        this.voteRepository = voteRepository;
        this.modelRepository = modelRepository;
        this.modelAliasRepository = modelAliasRepository;
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
                myVotedModelIds.contains(model.getId())))
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
     * alias of one (it is not something to request). Otherwise the model's
     * registry row is created if needed and the user's vote recorded. The
     * unique (model, user) index means a second vote by the same user is a
     * no-op — everyone still gets exactly one vote.
     *
     * @throws IllegalArgumentException when no name is given, the name is not
     *     in {@code provider/model} form, or it exceeds the maximum length
     * @throws ModelAlreadyAvailableException when the name is already in Logos
     */
    @Transactional
    public RequestedModelResponse vote(Integer userId, String name) {
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
        if (modelRepository.existsByNameIgnoreCase(normalized)
            || modelAliasRepository.existsByAliasIgnoreCase(normalized)) {
            throw new ModelAlreadyAvailableException("This model is already available in Logos.");
        }

        requestedModelRepository.lockRequestedModelsNamespace(REQUESTED_MODELS_NAMESPACE_LOCK_KEY);
        RequestedModel model = requestedModelRepository.findByNameIgnoreCase(normalized).orElseGet(() -> {
            RequestedModel created = new RequestedModel();
            created.setName(normalized);
            return created;
        });
        model = requestedModelRepository.save(model);

        if (!voteRepository.existsByRequestedModelIdAndUserId(model.getId(), userId)) {
            RequestedModelVote vote = new RequestedModelVote();
            vote.setRequestedModelId(model.getId());
            vote.setUserId(userId);
            voteRepository.save(vote);
        }
        return toResponse(model, (int) voteRepository.countByRequestedModelId(model.getId()), true);
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
            return new RequestedModelResponse(null, normalized, 0, false);
        }
        voteRepository.findByRequestedModelIdAndUserId(model.getId(), userId)
            .ifPresent(voteRepository::delete);
        if (voteRepository.countByRequestedModelId(model.getId()) == 0) {
            requestedModelRepository.delete(model);
            return new RequestedModelResponse(model.getId(), model.getName(), 0, false);
        }
        return toResponse(model, (int) voteRepository.countByRequestedModelId(model.getId()), false);
    }

    private RequestedModelResponse toResponse(RequestedModel model, int count, boolean hasVoted) {
        return new RequestedModelResponse(model.getId(), model.getName(), count, hasVoted);
    }

    private void requireUser(Integer userId) {
        if (userId == null) {
            throw new IllegalArgumentException("No user context.");
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
