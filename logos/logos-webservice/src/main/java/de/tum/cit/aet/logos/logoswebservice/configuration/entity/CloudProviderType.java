package de.tum.cit.aet.logos.logoswebservice.configuration.entity;

public enum CloudProviderType {
    azure, openai, anthropic, gemini, bedrock, deepseek, groq,
    /**
     * Another Logos instance used as an upstream. It serves every surface this one does,
     * including the Anthropic Messages API, so requests reach it unchanged instead of
     * being translated into an OpenAI dialect.
     */
    logos
}
