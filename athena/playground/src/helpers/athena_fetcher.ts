import baseUrl from "./base_url";

class FetchError extends Error {
  status: number;
  info: any;

  constructor(message: string, status: number, info: any) {
    super(message);
    this.name = "FetchError";
    this.status = status;
    this.info = info;
  }
}

const athenaFetcher =
  (athenaSecret: string, lmsUrl: string, moduleConfig: any = undefined) =>
  async (url: string) => {
    const res = await fetch(
      `${baseUrl}/api/athena_request?${new URLSearchParams({
        url: url,
      })}`,
      {
        method: "GET",
        headers: {
          "Content-Type": "application/json",
          "Authorization": athenaSecret,
          "X-Server-URL": lmsUrl,
          ...(moduleConfig && {
            "X-Module-Config": JSON.stringify(moduleConfig),
          }),
        },
      }
    );

    if (!res.ok) {
      throw new FetchError(
        "An error occurred while fetching the data.",
        res.status,
        await res.json()
      );
    }

    return res.json();
  };

export default athenaFetcher;
