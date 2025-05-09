import { useState } from "react";
import * as Collapsible from '@radix-ui/react-collapsible';
import { twMerge } from 'tailwind-merge'

type DisclosureProps = {
  title: string | JSX.Element | JSX.Element[],
  children: string | JSX.Element | JSX.Element[],
  className?: {
    root?: string,
    trigger?: string,
    content?: string,
  }
  openedInitially?: boolean,
  noContentIndent?: boolean,
}

export default function Disclosure({ title, children, className, openedInitially, noContentIndent }: DisclosureProps) {
  const [open, setOpen] = useState(openedInitially ?? false);

  return (
    <Collapsible.Root open={open} onOpenChange={setOpen} className={className?.root}>
      <Collapsible.Trigger className={twMerge("text-gray-500 font-medium", className?.trigger)}>
        <span className="inline-block transform transition-transform duration-200 mr-1" style={{ transform: open ? "rotate(90deg)" : "rotate(0deg)" }}>
          ▶
        </span>
        {title}
      </Collapsible.Trigger>
      <Collapsible.Content className={twMerge('mt-1', noContentIndent ? '' : 'ml-4', className?.content)}>
        {children}
      </Collapsible.Content>
    </Collapsible.Root>
  );
}