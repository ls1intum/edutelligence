def align_slides_with_segments(segments, slide_timestamps):
    result = []
    for segment in segments:
        slide_number = 1
        for ts, num in reversed(slide_timestamps):
            if ts <= segment["start"]:
                slide_number = num
                break
        result.append({
            "startTime": segment["start"],
            "endTime": segment["end"],
            "text": segment["text"].strip(),
            "slideNumber": slide_number
        })
    return result
