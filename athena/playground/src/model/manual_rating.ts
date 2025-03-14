export type ManualRating = {
  feedbackId: number;
  isAccepted?: boolean;
};

/**
 * Transforms a onManualRatingsChange function to a single onManualRatingChange function for a specific manual rating
 *
 * @param feedbackId - feedbackId for which the onManualRatingChange function should be created
 * @param manualRatings - manual ratings array
 * @param onManualRatingsChange - onManualRatingsChange function that should be transformed
 * @returns a onManualRatingChange function for the given feedback
 * @example
 *   const onManualRatingChange = createManualRatingItemUpdater(feedbackId, manualRatings, onManualRatingsChange);
 *   onManualRatingChange(newRating);
 */
export function createManualRatingItemUpdater(
  feedbackId: number,
  manualRatings: ManualRating[] | undefined,
  onManualRatingsChange: (manualRatings: ManualRating[]) => void
): (newManualRating: ManualRating | undefined) => void {
  return (newManualRating: ManualRating | undefined) => {
    let newManualRatings = [...(manualRatings ?? [])];
    const index = newManualRatings.findIndex((rating) => rating.feedbackId === feedbackId);
    if (newManualRating === undefined) {
      // Remove the rating if it exists
      if (index !== -1) {
        newManualRatings.splice(index, 1);
      }
    } else {
      if (index !== -1) {
        // Update existing rating
        newManualRatings[index] = newManualRating;
      } else {
        // Add new rating since it does not exist in the array
        newManualRatings.push(newManualRating);
      }
    }
    onManualRatingsChange(newManualRatings);
  };
}
