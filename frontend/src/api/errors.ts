export interface FieldError {
  field: string;
  code: string;
  message: string;
}

/** RFC 9457 problem+json from the backend (PRD 13.1.2), plus transport failures. */
export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
    readonly requestId: string | null = null,
    readonly errors: FieldError[] = [],
  ) {
    super(message);
    this.name = "ApiError";
  }
}
