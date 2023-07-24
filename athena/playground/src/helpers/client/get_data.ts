import type { Mode } from "@/model/mode";
import type { Exercise } from "@/model/exercise";
import type { Submission } from "@/model/submission";
import type { Feedback } from "@/model/feedback";

import useSWR from "swr";

import baseUrl from "@/helpers/base_url";
import fetcher from "@/helpers/fetcher";

export function useSubmissions(mode: Mode, exercise?: Exercise) {
  const { data, error, isLoading } = useSWR(() => {
    if (exercise === undefined) {
      return null;
    } else {
      return `${baseUrl}/api/mode/${mode}/exercise/${exercise.id}/submissions`;
    }
  }, fetcher);

  return {
    submissions: data as Submission[] | undefined,
    isLoading,
    error,
  };
}

export function useFeedbacks(mode: Mode, exercise?: Exercise) {
  const { data, error, isLoading } = useSWR(() => {
    if (exercise === undefined) {
      return null;
    } else {
      return `${baseUrl}/api/mode/${mode}/exercise/${exercise.id}/feedbacks`;
    }
  }, fetcher);

  return {
    feedbacks: data as Feedback[] | undefined,
    isLoading,
    error,
  };
}
