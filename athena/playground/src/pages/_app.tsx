import "@/styles/globals.css";
import "@/styles/schema_form.css";
import "@/styles/monaco.css";
import "@/styles/apollon.css";

import "@blueprintjs/core/lib/css/blueprint.css";
import "@blueprintjs/icons/lib/css/blueprint-icons.css";
import "allotment/dist/style.css";
import '@tumaet/apollon/dist/assets/style.css';

import type { AppProps } from "next/app";
import Head from "next/head";
import { QueryClient, QueryClientProvider } from "react-query"
import { BaseInfoProvider } from "@/hooks/base_info_context";

const queryClient = new QueryClient()

export default function App({ Component, pageProps }: AppProps) {
  return (
    <>
      <Head>
        <title>Athena Playground</title>
        <link rel="icon" href="/logo.png" sizes="any" />
      </Head>
      <QueryClientProvider client={queryClient}>
        <BaseInfoProvider>
          <Component {...pageProps} />
        </BaseInfoProvider>
      </QueryClientProvider>
      <footer className="p-4 text-gray-400 border-t border-gray-800 text-xs">
        {
          process.env.NEXT_PUBLIC_ATHENA_IS_DEVELOP === 'true' ? <>
            <span>develop</span>&nbsp;-&nbsp;
            <a href={`https://github.com/ls1intum/edutelligence/commit/${process.env.NEXT_PUBLIC_ATHENA_COMMIT_SHA}`} target="_blank" className="text-primary-500 hover:text-primary-400 hover:underline">
              Commit:&nbsp;{(process.env.NEXT_PUBLIC_ATHENA_COMMIT_SHA ?? '').slice(0, 7)}
            </a>&nbsp;-&nbsp;
            </> : (
            process.env.NEXT_PUBLIC_ATHENA_COMMIT_SHA ? <>
              <a href={`https://github.com/ls1intum/edutelligence/pull/${process.env.NEXT_PUBLIC_ATHENA_PR_NUMBER}`} target="_blank" className="text-primary-500 hover:text-primary-400 hover:underline">
                PR&nbsp;#{process.env.NEXT_PUBLIC_ATHENA_PR_NUMBER}:&nbsp;
                {process.env.NEXT_PUBLIC_ATHENA_PR_TITLE}
              </a>&nbsp;-&nbsp;
              <a href={`https://github.com/ls1intum/edutelligence/pull/${process.env.NEXT_PUBLIC_ATHENA_PR_NUMBER}/commits/${process.env.NEXT_PUBLIC_ATHENA_COMMIT_SHA}`} target="_blank" className="text-primary-500 hover:text-primary-400 hover:underline">
                Commit:&nbsp;{(process.env.NEXT_PUBLIC_ATHENA_COMMIT_SHA ?? '').slice(0, 7)}
              </a>&nbsp;-&nbsp;
              <span>
                Last update:&nbsp;{process.env.NEXT_PUBLIC_ATHENA_PR_LAST_UPDATE}
              </span>
            </> : (
              <span>Local build</span>
            )
          )
        }
      </footer>
    </>
  );
}
