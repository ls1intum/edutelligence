import {Button} from "@/components/ui/button";
import Link from "next/link";

export function Header() {

    return (
        <header className="mb-5">
            <div className="grid grid-cols-2 grid-flow-col gap-5 justify-items-end items-center">
                <h1 className="justify-self-start scroll-m-20 text-4xl font-extrabold tracking-tight lg:text-5xl">
                    Atlas Metrics
                </h1>
                <Button asChild>
                    <Link href="/login">Login</Link>
                </Button>
            </div>
        </header>
    )
}