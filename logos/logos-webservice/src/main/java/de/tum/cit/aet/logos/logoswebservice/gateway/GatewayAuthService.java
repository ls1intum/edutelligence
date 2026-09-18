package de.tum.cit.aet.logos.logoswebservice.gateway;

import java.util.Optional;

import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.web.server.ResponseStatusException;

/**
 * Loads an active Logos API key by its secret value.
 *
 * <p>Stateless: each call hits the database (no key cache). Revocation takes
 * effect on the next request. Prefer
 * {@link GatewayDeploymentRepository#authenticateAndFindDeploymentsForModel}
 * on the named-model cloud path so auth and permissions share one query.
 */
@Service
public class GatewayAuthService {

    private final GatewayDeploymentRepository deploymentRepository;

    public GatewayAuthService(GatewayDeploymentRepository deploymentRepository) {
        this.deploymentRepository = deploymentRepository;
    }

    /**
     * @throws ResponseStatusException 401 when the key is missing or inactive
     */
    public GatewayKey requireActiveKey(String keyValue) {
        if (keyValue == null || keyValue.isBlank()) {
            throw new ResponseStatusException(HttpStatus.UNAUTHORIZED, "Invalid or missing API key");
        }
        Optional<GatewayKey> key = deploymentRepository.findActiveKey(keyValue);
        if (key.isEmpty()) {
            throw new ResponseStatusException(HttpStatus.UNAUTHORIZED, "Invalid or missing API key");
        }
        return key.get();
    }

    /**
     * Single-query auth + deployments for a named model.
     *
     * @throws ResponseStatusException 401 when the key is missing or inactive
     */
    public GatewayAuthContext requireKeyAndDeployments(String keyValue, String modelName) {
        if (keyValue == null || keyValue.isBlank()) {
            throw new ResponseStatusException(HttpStatus.UNAUTHORIZED, "Invalid or missing API key");
        }
        return deploymentRepository.authenticateAndFindDeploymentsForModel(keyValue, modelName)
            .orElseThrow(() -> new ResponseStatusException(
                HttpStatus.UNAUTHORIZED, "Invalid or missing API key"));
    }
}
