export enum RequestType {
  GET = "GET",
  PUT = "PUT",
  POST = "POST",
  DELETE = "DELETE",
  PATCH = "PATCH",
  HEAD = "HEAD",
  OPTIONS = "OPTIONS",
  TRACE = "TRACE",
  CONNECT = "CONNECT",
}

export enum RequestCategory {
  READ = "READ",
  WRITE = "WRITE",
  CONNECT = "CONNECT",
}

export function mapRequestTypeToCategory(requestType: RequestType): RequestCategory {
  switch (requestType) {
    case RequestType.GET:
    case RequestType.HEAD:
    case RequestType.OPTIONS:
    case RequestType.TRACE:
      return RequestCategory.READ;
    case RequestType.POST:
    case RequestType.PUT:
    case RequestType.PATCH:
    case RequestType.DELETE:
      return RequestCategory.WRITE;
    case RequestType.CONNECT:
      return RequestCategory.CONNECT;
  }
}