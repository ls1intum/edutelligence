declare module 'mermaid' {
  interface MermaidConfig {
    startOnLoad?: boolean;
    securityLevel?: string;
    theme?: string;
    [key: string]: unknown;
  }

  interface MermaidApi {
    initialize(config: MermaidConfig): void;
    run(options: { querySelector?: string; nodes?: ArrayLike<HTMLElement> }): Promise<void>;
    render(id: string, text: string): Promise<{ svg: string }>;
  }

  const mermaid: MermaidApi;
  export default mermaid;
}
