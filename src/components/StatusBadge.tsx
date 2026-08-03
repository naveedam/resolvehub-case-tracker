import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

const TONE: Record<string, string> = {
  active: "bg-success/12 text-success border-success/30",
  open: "bg-success/12 text-success border-success/30",
  "under review": "bg-warning/15 text-warning-foreground border-warning/40",
  pending: "bg-warning/15 text-warning-foreground border-warning/40",
  scheduled: "bg-warning/15 text-warning-foreground border-warning/40",
  closed: "bg-muted text-muted-foreground border-border",
  auctioned: "bg-destructive/10 text-destructive border-destructive/30",
};

export function StatusBadge({ value }: { value: string | null }) {
  if (!value) return <span className="text-muted-foreground">—</span>;
  return (
    <Badge
      variant="outline"
      className={cn("font-medium", TONE[value.toLowerCase()] ?? "bg-secondary text-foreground")}
    >
      {value}
    </Badge>
  );
}