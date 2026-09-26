"use client";
import { useParams } from "next/navigation";
import { ReviewWorkspace } from "@/components/reviews/ReviewWorkspace";

export default function ReviewPage() {
  return <ReviewWorkspace id={String(useParams().reviewId)} />;
}
