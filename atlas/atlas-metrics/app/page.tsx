"use client";

import { SessionProvider } from "next-auth/react";
import Dashboard from "./dashboard/dashboard";

export default function Home() {
  return (
    <SessionProvider>
      <Dashboard />
    </SessionProvider>
  );
}
