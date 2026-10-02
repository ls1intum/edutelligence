package de.tum.cit.aet.logos.logoswebservice.gateway;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;

import org.springframework.http.HttpStatus;
import org.springframework.web.server.ResponseStatusException;

/**
 * Bounded body reads for the inference gateway.
 *
 * <p>Gateway paths bypass Spring multipart parsing and buffer with
 * {@link #read} so chunked uploads cannot exceed {@link #MAX_BYTES} before
 * allocation completes.
 */
final class GatewayBodyReader {

    /** 51 MiB — matches the orchestrator's practical upload ceiling. */
    static final long MAX_BYTES = 51L * 1024L * 1024L;

    private GatewayBodyReader() {
    }

    static byte[] read(InputStream in) throws IOException {
        if (in == null) {
            return new byte[0];
        }
        ByteArrayOutputStream buf = new ByteArrayOutputStream();
        byte[] chunk = new byte[8192];
        long total = 0;
        int n;
        while ((n = in.read(chunk)) >= 0) {
            total += n;
            if (total > MAX_BYTES) {
                throw new ResponseStatusException(
                    HttpStatus.PAYLOAD_TOO_LARGE,
                    "Request body exceeds " + MAX_BYTES + " bytes");
            }
            buf.write(chunk, 0, n);
        }
        return buf.toByteArray();
    }
}
