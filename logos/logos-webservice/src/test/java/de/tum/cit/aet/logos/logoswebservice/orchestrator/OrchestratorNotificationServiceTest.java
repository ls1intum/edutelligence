package de.tum.cit.aet.logos.logoswebservice.orchestrator;

import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import org.mockito.ArgumentCaptor;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.http.HttpEntity;
import org.springframework.test.util.ReflectionTestUtils;
import org.springframework.transaction.support.TransactionSynchronization;
import org.springframework.transaction.support.TransactionSynchronizationManager;
import org.springframework.transaction.support.TransactionSynchronizationUtils;
import org.springframework.web.client.RestTemplate;

/**
 * The orchestrator answers a refresh by reading the database back. Announcing a change before
 * its transaction commits is a race it loses on its own connection — it reads the rows as they
 * were, finds nothing to do, and the operator is left with the empty model list the cloud model
 * sync exists to prevent.
 */
class OrchestratorNotificationServiceTest {

    private RestTemplate restTemplate;
    private OrchestratorNotificationService service;

    @BeforeEach
    void setUp() {
        restTemplate = mock(RestTemplate.class);
        // The real bean resolves itself through the proxy so the send stays @Async. A unit test
        // has no proxy, so it resolves to the instance itself and the send runs inline — which
        // is what makes the ordering observable here.
        service = new OrchestratorNotificationService(restTemplate, providerOf());
        ReflectionTestUtils.setField(service, "orchestratorUrl", "http://orchestrator:8000");
        ReflectionTestUtils.setField(service, "internalSecret", "s3cret");
    }

    @AfterEach
    void tearDown() {
        if (TransactionSynchronizationManager.isSynchronizationActive()) {
            TransactionSynchronizationManager.clearSynchronization();
        }
    }

    private ObjectProvider<OrchestratorNotificationService> providerOf() {
        @SuppressWarnings("unchecked")
        ObjectProvider<OrchestratorNotificationService> provider = mock(ObjectProvider.class);
        org.mockito.Mockito.lenient().when(provider.getObject()).thenAnswer(invocation -> service);
        return provider;
    }

    @Test
    void sendsImmediatelyWhenNoTransactionIsInProgress() {
        service.notifyRefresh(false, true);

        verify(restTemplate).postForEntity(eq("http://orchestrator:8000/internal/refresh_pipeline"), any(), any());
    }

    @Test
    void doesNotAnnounceAChangeThatHasNotCommittedYet() {
        TransactionSynchronizationManager.initSynchronization();

        service.notifyRefresh(false, true);

        verify(restTemplate, never()).postForEntity(any(String.class), any(), any());
    }

    @Test
    void announcesTheChangeOnceItsTransactionCommits() {
        TransactionSynchronizationManager.initSynchronization();
        service.notifyRefresh(false, true);

        TransactionSynchronizationUtils.triggerAfterCommit();

        ArgumentCaptor<HttpEntity<Map<String, Object>>> body = captor();
        verify(restTemplate).postForEntity(
            eq("http://orchestrator:8000/internal/refresh_pipeline"), body.capture(), any());
        assertThat(body.getValue().getBody())
            .containsEntry("sync_cloud_models", true)
            .containsEntry("rebuild_classifier", false);
    }

    @Test
    void announcesNothingWhenTheTransactionRollsBack() {
        TransactionSynchronizationManager.initSynchronization();
        service.notifyRefresh(true, false);

        // afterCommit never runs for a rollback; only the completion callbacks do.
        TransactionSynchronizationUtils.triggerAfterCompletion(TransactionSynchronization.STATUS_ROLLED_BACK);

        verify(restTemplate, never()).postForEntity(any(String.class), any(), any());
    }

    @Test
    void staysQuietWhenNoOrchestratorIsConfigured() {
        ReflectionTestUtils.setField(service, "orchestratorUrl", "");

        service.notifyRefresh(false, true);

        verify(restTemplate, never()).postForEntity(any(String.class), any(), any());
    }

    @SuppressWarnings({"unchecked", "rawtypes"})
    private static ArgumentCaptor<HttpEntity<Map<String, Object>>> captor() {
        return (ArgumentCaptor) ArgumentCaptor.forClass(HttpEntity.class);
    }
}
