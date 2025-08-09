import React, { useEffect, useState } from 'react';
import { v4 as uuidv4 } from 'uuid';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import { faCheck, faCopy, faPlus, faSyncAlt, faTrash } from '@fortawesome/free-solid-svg-icons';
import baseUrl from '@/helpers/base_url';
import { fetchExpertEvaluationProgressStats } from '@/hooks/playground/expert_evaluation_progress_stats';
import { ExpertEvaluationProgressStats } from "@/model/expert_evaluation_progress_stats";

type ExpertLinksProps = {
  expertIds: string[];
  setExpertIds: (newExpertIds: string[]) => void;
  started: boolean;
  configId: string;
};

export default function ExpertLinks(props: ExpertLinksProps) {
  const { expertIds, setExpertIds, started, configId } = props;

  const [copiedLink, setCopiedLink] = useState<string | null>(null);
  const [progressStats, setProgressStats] = useState<ExpertEvaluationProgressStats>();
  const [loading, setLoading] = useState(false);

  const updateProgressStats = async () => {
    setLoading(true);
    const minimumDelay = new Promise((resolve) => setTimeout(resolve, 1000));
    try {
      const statsPromise = fetchExpertEvaluationProgressStats(configId);
      const [stats] = await Promise.all([statsPromise, minimumDelay]);
      setProgressStats(stats);
    } catch (error) {
      console.error('Failed to fetch progress stats:', error);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (started) updateProgressStats();
  }, [configId, started]);

  const addExpertId = () => setExpertIds([...expertIds, uuidv4()]);

  const copyLink = (link: string) => {
    navigator.clipboard.writeText(link);
    setCopiedLink(link);
    setTimeout(() => setCopiedLink(null), 2000);
  };

  const deleteExpertId = (id: string) => setExpertIds(expertIds.filter((expertId) => expertId !== id));

  return (
    <section className="flex flex-col">
      <div className="flex justify-between items-center mb-2">
        <span className="text-lg font-bold">Expert Links</span>
        {/* Add New Expert and Conditional Update Stats Button */}
        <div className="flex gap-2">
          <button
            className="bg-green-500 text-white rounded-md p-2 hover:bg-green-600 flex items-center gap-2"
            onClick={addExpertId}
          >
            <FontAwesomeIcon icon={faPlus} />
            Add New Expert
          </button>
          {started && (
            <button
              className="bg-blue-500 text-white rounded-md p-2 hover:bg-blue-600 flex items-center gap-2"
              onClick={updateProgressStats}
              disabled={loading}
            >
              <FontAwesomeIcon icon={faSyncAlt} spin={loading} />
              Update Progress
            </button>
          )}
        </div>
      </div>

      {/* List of Expert Links */}
      <ul className="space-y-2">
        {expertIds.length ? (
          expertIds.map((expertId) => {
            const expertLink = `${window.location.origin}${baseUrl}/${configId}/${expertId}/expert_view`;
            const completed = progressStats?.[expertId] ?? 0;
            const total = progressStats?.totalSubmissions ?? 0;
            const progressPercentage = total ? (completed / total) * 100 : 0;

            return (
              <li key={expertId} className="flex flex-col border p-2 rounded-md shadow-sm space-y-1">
                <div className="flex justify-between items-center">
                  <a href={expertLink} target="_blank" rel="noopener noreferrer" className="text-blue-500 underline">
                    {expertLink}
                  </a>
                  <div className="flex space-x-2">
                    {/* Copy Link Button */}
                    <button
                      className="bg-blue-500 text-white rounded-md p-2 hover:bg-blue-600"
                      onClick={() => copyLink(expertLink)}
                      title="Copy Link"
                    >
                      <FontAwesomeIcon icon={copiedLink === expertLink ? faCheck : faCopy} />
                    </button>
                    {/* Delete Button */}
                    {!started && (
                      <button
                        className="bg-red-500 text-white rounded-md p-2 hover:bg-red-600"
                        onClick={() => deleteExpertId(expertId)}
                        title="Delete Link"
                      >
                        <FontAwesomeIcon icon={faTrash} />
                      </button>
                    )}
                  </div>
                </div>

                {/* Progress Bar */}
                {started && (
                  <>
                    <div className="relative w-full bg-gray-300 h-2 rounded mt-1">
                      <div className="bg-blue-500 h-2 rounded" style={{ width: `${progressPercentage}%` }} />
                    </div>
                    <span className="text-sm text-gray-700">
                      {completed === 0 ? 'Not started' : completed === total ? 'Finished 🏁' : `${completed} / ${total} completed`}
                    </span>
                  </>
                )}
              </li>
            );
          })
        ) : (
          <li className="border p-2 rounded-md shadow-sm bg-gray-50 text-center">No expert links added</li>
        )}
      </ul>
    </section>
  );
}
