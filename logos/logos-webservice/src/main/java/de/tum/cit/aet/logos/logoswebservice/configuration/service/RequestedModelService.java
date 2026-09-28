package de.tum.cit.aet.logos.logoswebservice.configuration.service;

import java.util.Comparator;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;

import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import de.tum.cit.aet.logos.logoswebservice.configuration.dto.RequestedModelResponse;
import de.tum.cit.aet.logos.logoswebservice.configuration.entity.RequestedModel;
import de.tum.cit.aet.logos.logoswebservice.configuration.entity.RequestedModelVote;
import de.tum.cit.aet.logos.logoswebservice.configuration.repository.ModelRepository;
import de.tum.cit.aet.logos.logoswebservice.configuration.repository.RequestedModelRepository;
import de.tum.cit.aet.logos.logoswebservice.configuration.repository.RequestedModelVoteRepository;

/**
 * The model-request voting feature: record demand for models Logos does not
 * serve yet, and show what everyone has asked for.
 *
 * This is a demand signal, not a configuration change — nothing here provisions
 * a model. Each user gets one vote per requested model; they can take the vote
 * back and cast it again. A model an admin later adds to {@code models} is no
 * longer "requested": voting for it is refused and it drops out of the listing.
 */
@Service
public class RequestedModelService {

    /**
     * Arbitrary stable key identifying the requested-model name namespace to
     * {@code pg_advisory_xact_lock}; the value itself is meaningless.
     */
    private static final long REQUESTED_MODELS_NAMESPACE_LOCK_KEY = 0x5245514D4F444C53L; // "REQMODLS"

    /** Raised when a vote is cast for a model that is already served by Logos. */
    public static class ModelAlreadyAvailableException extends RuntimeException {
        public ModelAlreadyAvailableException(String message) {
            super(message);
        }
    }

    private final RequestedModelRepository requestedModelRepository;
    private final RequestedModelVoteRepository voteRepository;
    private final ModelRepository modelRepository;

    public RequestedModelService(RequestedModelRepository requestedModelRepository,
                                 RequestedModelVoteRepository voteRepository,
                                 ModelRepository modelRepository) {
        this.requestedModelRepository = requestedModelRepository;
        this.voteRepository = voteRepository;
        this.modelRepository = modelRepository;
    }

    /**
     * Every requested model that is not yet served by Logos, most-voted first
     * (ties broken by name). Each entry carries its vote count and whether the
     * given user has voted for it, so the page can render the vote/undo control.
     */
    public List<RequestedModelResponse> list(Integer userId) {
        Set<String> available = modelRepository.findAll().stream()
            .map(model -> model.getName().toLowerCase(Locale.ROOT))
            .collect(java.util.stream.Collectors.toSet());

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
     * Refused when the model is already served by Logos (it is not something to
     * request). Otherwise the model's registry row is created if needed and the
     * user's vote recorded. The unique (model, user) index means a second vote
     * by the same user is a no-op — everyone still gets exactly one vote.
     *
     * @throws IllegalArgumentException when no name is given
     * @throws ModelAlreadyAvailableException when the model is already in Logos
     */
    @Transactional
    public RequestedModelResponse vote(Integer userId, String name) {
        if (name == null || name.isBlank()) {
            throw new IllegalArgumentException("A model name is required.");
        }
        requireUser(userId);
        String trimmed = name.strip();
        if (modelRepository.existsByNameIgnoreCase(trimmed)) {
            throw new ModelAlreadyAvailableException("This model is already available in Logos.");
        }

        requestedModelRepository.lockRequestedModelsNamespace(REQUESTED_MODELS_NAMESPACE_LOCK_KEY);
        RequestedModel model = requestedModelRepository.findByNameIgnoreCase(trimmed).orElseGet(() -> {
            RequestedModel created = new RequestedModel();
            created.setName(trimmed);
            return created;
        });
        model = requestedModelRepository.save(model);

        if (!voteRepository.existsByRequestedModelIdAndUserId(model.getId(), userId)) {
            RequestedModelVote vote = new RequestedModelVote();
            vote.setRequestedModelId(model.getId());
            vote.setUserId(userId);
            voteRepository.save(vote);
        }
        return toResponse(model, (int) voteRepository.countByRequestedModelId(model.getId()));
    }

    /**
     * Take the user's vote back for a model.
     *
     * Idempotent: undoing a vote that is not there (unknown model, or the user
     * did not vote) is a no-op. When a model's last vote is removed, its
     * registry row goes with it, so the list never shows a model nobody wants.
     *
     * @throws IllegalArgumentException when no name is given
     */
    @Transactional
    public RequestedModelResponse undo(Integer userId, String name) {
        if (name == null || name.isBlank()) {
            throw new IllegalArgumentException("A model name is required.");
        }
        requireUser(userId);
        String trimmed = name.strip();

        requestedModelRepository.lockRequestedModelsNamespace(REQUESTED_MODELS_NAMESPACE_LOCK_KEY);
        RequestedModel model = requestedModelRepository.findByNameIgnoreCase(trimmed).orElse(null);
        if (model == null) {
            return new RequestedModelResponse(null, trimmed, 0, false);
        }
        voteRepository.findByRequestedModelIdAndUserId(model.getId(), userId)
            .ifPresent(voteRepository::delete);
        if (voteRepository.countByRequestedModelId(model.getId()) == 0) {
            requestedModelRepository.delete(model);
            return new RequestedModelResponse(model.getId(), model.getName(), 0, false);
        }
        return toResponse(model, (int) voteRepository.countByRequestedModelId(model.getId()));
    }

    private RequestedModelResponse toResponse(RequestedModel model, int count) {
        return new RequestedModelResponse(model.getId(), model.getName(), count, true);
    }

    private void requireUser(Integer userId) {
        if (userId == null) {
            throw new IllegalArgumentException("No user context.");
        }
    }
}
