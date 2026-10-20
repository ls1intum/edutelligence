package de.tum.cit.aet.logos.logoswebservice.gateway;

import static org.assertj.core.api.Assertions.assertThat;

import org.junit.jupiter.api.Test;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;

class GatewayReasoningEffortTest {

    private final ObjectMapper mapper = new ObjectMapper();

    private String effort(String json) throws Exception {
        JsonNode root = mapper.readTree(json);
        return GatewayReasoningEffort.from(root);
    }

    @Test
    void readsTheChatCompletionsField() throws Exception {
        assertThat(effort("{\"model\":\"m\",\"reasoning_effort\":\"High\"}")).isEqualTo("high");
    }

    @Test
    void readsTheResponsesApiField() throws Exception {
        assertThat(effort("{\"model\":\"m\",\"reasoning\":{\"effort\":\"low\",\"summary\":\"auto\"}}"))
            .isEqualTo("low");
    }

    @Test
    void readsTheMessagesApiField() throws Exception {
        assertThat(effort("{\"model\":\"m\",\"output_config\":{\"effort\":\"xhigh\"}}")).isEqualTo("xhigh");
    }

    @Test
    void readsTheTemplateKwarg() throws Exception {
        assertThat(effort("{\"model\":\"m\",\"chat_template_kwargs\":{\"reasoning_effort\":\"medium\"}}"))
            .isEqualTo("medium");
    }

    @Test
    void prefersTheTopLevelFieldAndSkipsBlankOnes() throws Exception {
        assertThat(effort("{\"reasoning_effort\":\"minimal\",\"reasoning\":{\"effort\":\"high\"}}"))
            .isEqualTo("minimal");
        assertThat(effort("{\"reasoning_effort\":\" \",\"reasoning\":{\"effort\":\"high\"}}"))
            .isEqualTo("high");
    }

    @Test
    void isNullWithoutAnEffort() throws Exception {
        assertThat(effort("{\"model\":\"m\",\"messages\":[]}")).isNull();
        assertThat(effort("{\"reasoning\":null,\"reasoning_effort\":3}")).isNull();
        assertThat(effort("[1,2]")).isNull();
        assertThat(GatewayReasoningEffort.from(null)).isNull();
    }
}
