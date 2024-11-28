"use client";

import { signIn, signOut, useSession } from "next-auth/react";
import { Button } from "@/components/ui/button";

export function AuthButton() {
  const { data: session } = useSession();
  if (session) {
    return <Button onClick={() => signOut()}>Logout</Button>;
  } else {
    return <Button onClick={() => signIn("github")}>Login</Button>;
  }
}
