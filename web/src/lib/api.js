/** An HTTP error from the review API, keeping what the caller needs to answer it. */
export class ApiError extends Error {
  /**
   * @param {string} message
   * @param {number} status
   * @param {unknown} payload the parsed JSON body (`{ error?: string, version?: string }` for this API)
   */
  constructor(message, status, payload) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.payload = payload;
  }
}
