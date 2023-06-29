import useSWR from "swr";

import { Mode } from "@/model/mode";
import { Exercise } from "@/model/exercise";
import { Submission } from "@/model/submission";
import Feedback from "@/model/feedback";

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
