import { AuthButton } from "@components/custom/AuthButton";
import {Nav} from "@components/custom/Nav";

export function Header() {
  return (
    <header className="mb-5">
      <div className="grid grid-flow-col grid-cols-2 items-center justify-items-end gap-5">
        <h1 className="scroll-m-20 justify-self-start text-4xl font-extrabold tracking-tight lg:text-5xl">
          Atlas Metrics
        </h1>
          <div className="justify-self-start">
              <Nav />
          </div>
        <AuthButton />
      </div>
    </header>
  );
}
