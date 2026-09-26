import { apiFetch, json } from "./client";
import type { Course, Offering, Test, Question, ModelAnswer, GradingPolicy, Rubric, Material, SampleAnswer, Student, Submission, Readiness, Job } from "@/types/domain";
export const courses = { list: () => apiFetch<Course[]>("/courses"), get: (id: string) => apiFetch<Course>(`/courses/${id}`), create: (v: unknown) => apiFetch<Course>("/courses", json(v)), update: (id: string, v: unknown) => apiFetch<Course>(`/courses/${id}`, { ...json(v), method: "PATCH" }) };
export const offerings = { list: (cid: string) => apiFetch<Offering[]>(`/courses/${cid}/offerings`), get: (id: string) => apiFetch<Offering>(`/offerings/${id}`), create: (cid: string, v: unknown) => apiFetch<Offering>(`/courses/${cid}/offerings`, json(v)) };
export const tests = { list: (oid: string) => apiFetch<Test[]>(`/offerings/${oid}/tests`), get: (id: string) => apiFetch<Test>(`/tests/${id}`), create: (oid: string, v: unknown) => apiFetch<Test>(`/offerings/${oid}/tests`, json(v)) };
export const questions = { list: (tid: string) => apiFetch<Question[]>(`/tests/${tid}/questions`), create: (tid: string, v: unknown) => apiFetch<Question>(`/tests/${tid}/questions`, json(v)), update: (id: string, v: unknown) => apiFetch<Question>(`/questions/${id}`, { ...json(v), method: "PATCH" }) };
export const testData = {
  materials: (id: string) => apiFetch<Material[]>(`/tests/${id}/materials`),
  materialFileUrl: (testId: string, materialId: string) => `${(process.env.NEXT_PUBLIC_API_BASE_URL || "/api/v1").replace(/\/$/, "")}/tests/${encodeURIComponent(testId)}/materials/${encodeURIComponent(materialId)}/file`,
  createMaterial: (id: string, v: unknown) => apiFetch<Material>(`/tests/${id}/materials`, json(v)),
  answers: (id: string) => apiFetch<ModelAnswer[]>(`/tests/${id}/model-answers`),
  createAnswer: (id: string, v: unknown) => apiFetch<ModelAnswer>(`/tests/${id}/model-answers`, json(v)),
  policies: (id: string) => apiFetch<GradingPolicy[]>(`/tests/${id}/grading-policies`),
  createPolicy: (id: string, v: unknown) => apiFetch<GradingPolicy>(`/tests/${id}/grading-policies`, json(v)),
  rubrics: (id: string) => apiFetch<Rubric[]>(`/tests/${id}/rubrics`),
  createRubric: (id: string, v: unknown) => apiFetch<Rubric>(`/tests/${id}/rubrics`, json(v)),
  approveRubric: (id: string, v: unknown) => apiFetch<Rubric>(`/rubrics/${id}/approve`, json(v)),
  samples: (id: string) => apiFetch<SampleAnswer[]>(`/tests/${id}/sample-answers`),
  createSample: (id: string, v: unknown) => apiFetch<SampleAnswer>(`/tests/${id}/sample-answers`, json(v)),
  createSampleScore: (id: string, v: unknown) => apiFetch<unknown>(`/sample-answers/${id}/scores`, json(v)),
  students: (oid: string) => apiFetch<Student[]>(`/offerings/${oid}/students`),
  createStudent: (oid: string, v: unknown) => apiFetch<Student>(`/offerings/${oid}/students`, json(v)),
  submissions: (id: string) => apiFetch<Submission[]>(`/tests/${id}/submissions`),
  createSubmission: (id: string, v: unknown) => apiFetch<Submission>(`/tests/${id}/submissions`, json(v)),
  readiness: (id: string) => apiFetch<Readiness>(`/tests/${id}/readiness`),
  jobs: (id: string) => apiFetch<Job[]>(`/tests/${id}/grading-jobs`),
};
