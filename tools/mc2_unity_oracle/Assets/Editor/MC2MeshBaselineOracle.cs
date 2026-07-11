using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Runtime.ExceptionServices;
using System.Text;
using MagicaCloth2;
using Unity.Burst;
using Unity.Collections;
using Unity.Mathematics;
using UnityEditor;
using UnityEngine;

namespace HoTools.MC2Oracle.Editor
{
    public static class MC2MeshBaselineOracle
    {
        private const string MC2Version = "2.18.1";
        private const string MC2Commit = "418f89ff31a45bb4b2336641ad5907a1110eabea";

        private sealed class OracleCase
        {
            public string Id;
            public float3[] Positions;
            public byte[] Attributes;
            public int2[] Edges;
            public int3[] Triangles;
            public int[][] Adjacency;
            public bool CompareToHoTools = true;
            public string Note = string.Empty;
        }

        private sealed class OracleDump
        {
            public byte[] FinalAttributes;
            public int[] Parents;
            public int2[] ChildRanges;
            public int[] ChildData;
            public byte[] BaselineFlags;
            public int2[] BaselineRanges;
            public int[] BaselineData;
            public int[] Roots;
            public float[] Depths;
            public float3[] LocalPositions;
            public float4[] LocalRotations;
        }

        private sealed class ProxyCase
        {
            public string Id;
            public float3[] Positions;
            public float3[] Normals;
            public float3[] Tangents;
            public float2[] Uvs;
            public byte[] Attributes;
            public int2[] Lines = Array.Empty<int2>();
            public int3[] Triangles = Array.Empty<int3>();
            public string Note = string.Empty;
        }

        private sealed class ProxyDump
        {
            public byte[] FinalAttributes;
            public int3[] Triangles;
            public int2[] Edges;
            public int2[] VertexToVertexRanges;
            public int[] VertexToVertexData;
            public int2[][] VertexToTriangleRecords;
            public float3[] LocalNormals;
            public float3[] LocalTangents;
            public float3[] VertexBindPosePositions;
            public float4[] VertexBindPoseRotations;
        }

        private sealed class DistanceCase
        {
            public string Id;
            public float3[] Positions;
            public byte[] Attributes;
            public int[] Parents;
            public int2[] Edges;
            public int3[] Triangles;
            public int[][] Adjacency;
            public string Note = string.Empty;
        }

        private sealed class DistanceDump
        {
            public uint[] PackedIndices;
            public int2[] Ranges;
            public int[] Targets;
            public float[] RestSigned;
        }

        private sealed class DistanceRuntimeCase
        {
            public string Id;
            public int[] Targets;
            public float[] RestSigned;
            public string Note = string.Empty;
        }

        private sealed class DistanceRuntimeDump
        {
            public float3[] NextPositions;
            public float3[] VelocityPositions;
        }

        public static void RunBatch()
        {
            string outputDirectory = CommandLineValue("-mc2OracleOutput");
            if (string.IsNullOrWhiteSpace(outputDirectory))
            {
                outputDirectory = Path.Combine(
                    Directory.GetParent(Application.dataPath).FullName,
                    "OracleOutput"
                );
            }
            Directory.CreateDirectory(outputDirectory);

            int written = 0;
            foreach (OracleCase oracleCase in Cases())
            {
                OracleDump dump = RunCase(oracleCase);
                string json = BuildJson(oracleCase, dump);
                string path = Path.Combine(outputDirectory, oracleCase.Id + ".json");
                File.WriteAllText(path, json, new UTF8Encoding(false));
                Debug.Log($"[MC2 Oracle] wrote {path}");
                written++;
            }

            int proxyWritten = 0;
            foreach (ProxyCase proxyCase in ProxyCases())
            {
                ProxyDump dump = RunProxyCase(proxyCase);
                string json = BuildProxyJson(proxyCase, dump);
                string path = Path.Combine(outputDirectory, proxyCase.Id + ".json");
                File.WriteAllText(path, json, new UTF8Encoding(false));
                Debug.Log($"[MC2 Oracle] wrote {path}");
                proxyWritten++;
            }

            int distanceWritten = 0;
            foreach (DistanceCase distanceCase in DistanceCases())
            {
                DistanceDump dump = RunDistanceCase(distanceCase);
                string json = BuildDistanceJson(distanceCase, dump);
                string path = Path.Combine(outputDirectory, distanceCase.Id + ".json");
                File.WriteAllText(path, json, new UTF8Encoding(false));
                Debug.Log($"[MC2 Oracle] wrote {path}");
                distanceWritten++;
            }

            int distanceRuntimeWritten = 0;
            foreach (DistanceRuntimeCase runtimeCase in DistanceRuntimeCases())
            {
                DistanceRuntimeDump dump = RunDistanceRuntimeCase(runtimeCase);
                string json = BuildDistanceRuntimeJson(runtimeCase, dump);
                string path = Path.Combine(outputDirectory, runtimeCase.Id + ".json");
                File.WriteAllText(path, json, new UTF8Encoding(false));
                Debug.Log($"[MC2 Oracle] wrote {path}");
                distanceRuntimeWritten++;
            }

            Debug.Log(
                $"[MC2 Oracle] PASS: {written} Tier A Mesh baseline fixtures, "
                + $"{proxyWritten} proxy fixtures, {distanceWritten} distance fixtures, "
                + $"{distanceRuntimeWritten} distance runtime fixtures"
            );
        }

        private static OracleDump RunCase(OracleCase oracleCase)
        {
            using (var mesh = new VirtualMesh(oracleCase.Id))
            {
                int count = oracleCase.Positions.Length;
                mesh.isBoneCloth = false;
                mesh.localPositions = new ExSimpleNativeArray<float3>(oracleCase.Positions);
                mesh.localNormals = new ExSimpleNativeArray<float3>(
                    Enumerable.Repeat(new float3(0.0f, 0.0f, 1.0f), count).ToArray()
                );
                mesh.localTangents = new ExSimpleNativeArray<float3>(
                    Enumerable.Repeat(new float3(1.0f, 0.0f, 0.0f), count).ToArray()
                );
                mesh.uv = new ExSimpleNativeArray<float2>(new float2[count]);
                mesh.attributes = new ExSimpleNativeArray<VertexAttribute>(
                    oracleCase.Attributes.Select(value => new VertexAttribute(value)).ToArray()
                );

                BuildAdjacency(oracleCase.Adjacency, out uint[] indexArray, out ushort[] dataArray);
                mesh.vertexToVertexIndexArray = new NativeArray<uint>(indexArray, Allocator.Persistent);
                mesh.vertexToVertexDataArray = new NativeArray<ushort>(dataArray, Allocator.Persistent);

                InvokePrivate(mesh, "CreateMeshBaseLine");
                InvokePrivate(mesh, "CreateBaseLinePose");
                InvokePrivate(mesh, "CreateVertexRootAndDepth");

                return ReadDump(mesh);
            }
        }

        private static ProxyDump RunProxyCase(ProxyCase proxyCase)
        {
            using (var mesh = new VirtualMesh(proxyCase.Id))
            {
                int count = proxyCase.Positions.Length;
                mesh.isBoneCloth = false;
                mesh.meshType = VirtualMesh.MeshType.NormalMesh;
                mesh.localPositions = new ExSimpleNativeArray<float3>(proxyCase.Positions);
                mesh.localNormals = new ExSimpleNativeArray<float3>(proxyCase.Normals);
                mesh.localTangents = new ExSimpleNativeArray<float3>(proxyCase.Tangents);
                mesh.uv = new ExSimpleNativeArray<float2>(proxyCase.Uvs);
                mesh.attributes = new ExSimpleNativeArray<VertexAttribute>(
                    proxyCase.Attributes.Select(value => new VertexAttribute(value)).ToArray()
                );
                mesh.referenceIndices = new ExSimpleNativeArray<int>(
                    Enumerable.Range(0, count).ToArray()
                );
                mesh.boneWeights = new ExSimpleNativeArray<VirtualMeshBoneWeight>(
                    Enumerable
                        .Repeat(
                            new VirtualMeshBoneWeight(
                                new int4(0, 0, 0, 0),
                                new float4(1.0f, 0.0f, 0.0f, 0.0f)
                            ),
                            count
                        )
                        .ToArray()
                );
                mesh.triangles = new ExSimpleNativeArray<int3>(proxyCase.Triangles);
                mesh.lines = new ExSimpleNativeArray<int2>(proxyCase.Lines);
                mesh.initLocalToWorld = float4x4.identity;
                mesh.initWorldToLocal = float4x4.identity;
                mesh.initRotation = quaternion.identity;
                mesh.initInverseRotation = quaternion.identity;
                mesh.initScale = new float3(1.0f, 1.0f, 1.0f);
                mesh.boundingBox = new NativeReference<AABB>(Allocator.Persistent);

                var sdata = new ClothSerializeData();
                var recordObject = new GameObject(proxyCase.Id + "_record");
                try
                {
                    var record = new TransformRecord(recordObject.transform, true);
                    mesh.ConvertProxyMesh(
                        sdata,
                        record,
                        new List<TransformRecord>(),
                        record
                    );
                    if (mesh.result.IsError())
                    {
                        throw new InvalidOperationException(
                            $"ConvertProxyMesh failed for {proxyCase.Id}: {mesh.result.Result}"
                        );
                    }
                    return ReadProxyDump(mesh);
                }
                finally
                {
                    UnityEngine.Object.DestroyImmediate(recordObject);
                }
            }
        }

        private static DistanceDump RunDistanceCase(DistanceCase distanceCase)
        {
            using (var mesh = new VirtualMesh(distanceCase.Id))
            {
                mesh.isBoneCloth = false;
                mesh.localPositions = new ExSimpleNativeArray<float3>(distanceCase.Positions);
                mesh.attributes = new ExSimpleNativeArray<VertexAttribute>(
                    distanceCase.Attributes.Select(value => new VertexAttribute(value)).ToArray()
                );
                mesh.vertexParentIndices = new NativeArray<int>(
                    distanceCase.Parents,
                    Allocator.Persistent
                );
                mesh.edges = new NativeArray<int2>(distanceCase.Edges, Allocator.Persistent);
                mesh.triangles = new ExSimpleNativeArray<int3>(distanceCase.Triangles);

                BuildAdjacency(
                    distanceCase.Adjacency,
                    out uint[] vertexToVertexIndices,
                    out ushort[] vertexToVertexData
                );
                mesh.vertexToVertexIndexArray = new NativeArray<uint>(
                    vertexToVertexIndices,
                    Allocator.Persistent
                );
                mesh.vertexToVertexDataArray = new NativeArray<ushort>(
                    vertexToVertexData,
                    Allocator.Persistent
                );
                mesh.edgeToTriangles = BuildEdgeToTriangles(distanceCase.Triangles);

                DistanceConstraint.ConstraintData data = DistanceConstraint.CreateData(
                    mesh,
                    new ClothParameters()
                );
                uint[] packed = data.indexArray ?? Array.Empty<uint>();
                var ranges = new int2[packed.Length];
                for (int index = 0; index < packed.Length; index++)
                {
                    DataUtility.Unpack12_20(packed[index], out int count, out int start);
                    ranges[index] = new int2(start, count);
                }
                return new DistanceDump
                {
                    PackedIndices = packed,
                    Ranges = ranges,
                    Targets = (data.dataArray ?? Array.Empty<ushort>())
                        .Select(value => (int)value)
                        .ToArray(),
                    RestSigned = data.distanceArray ?? Array.Empty<float>(),
                };
            }
        }

        private static NativeParallelMultiHashMap<int2, ushort> BuildEdgeToTriangles(
            int3[] triangles
        )
        {
            var map = new NativeParallelMultiHashMap<int2, ushort>(
                Math.Max(1, triangles.Length * 3),
                Allocator.Persistent
            );
            for (int triangleIndex = 0; triangleIndex < triangles.Length; triangleIndex++)
            {
                int3 triangle = triangles[triangleIndex];
                foreach (int2 edge in new[]
                {
                    SortedEdge(triangle.x, triangle.y),
                    SortedEdge(triangle.y, triangle.z),
                    SortedEdge(triangle.z, triangle.x),
                })
                {
                    map.Add(edge, checked((ushort)triangleIndex));
                }
            }
            return map;
        }

        private static int2 SortedEdge(int x, int y)
        {
            return x <= y ? new int2(x, y) : new int2(y, x);
        }

        private static DistanceRuntimeDump RunDistanceRuntimeCase(
            DistanceRuntimeCase runtimeCase
        )
        {
            MethodInfo method = typeof(DistanceConstraint).GetMethod(
                "SolverConstraint",
                BindingFlags.Static | BindingFlags.NonPublic
            );
            if (method == null)
            {
                throw new MissingMethodException(
                    typeof(DistanceConstraint).FullName,
                    "SolverConstraint"
                );
            }

            var team = new TeamManager.TeamData
            {
                initScale = new float3(1.0f),
                scaleRatio = 1.0f,
                animationPoseRatio = 0.0f,
                proxyCommonChunk = new DataChunk(0, 3),
                particleChunk = new DataChunk(0, 3),
                distanceStartChunk = new DataChunk(0, 3),
                distanceDataChunk = new DataChunk(0, runtimeCase.Targets.Length),
            };
            var parameters = new ClothParameters();
            parameters.distanceConstraint.Convert(
                new DistanceConstraint.SerializeData(),
                ClothProcess.ClothType.MeshCloth
            );

            var attributes = new NativeArray<VertexAttribute>(
                new[]
                {
                    VertexAttribute.Move,
                    VertexAttribute.Fixed,
                    VertexAttribute.Fixed,
                },
                Allocator.Persistent
            );
            var depths = new NativeArray<float>(
                new[] { 0.5f, 0.0f, 0.0f },
                Allocator.Persistent
            );
            var nextPositions = new NativeArray<float3>(
                P((0, 0, 0), (2, 0, 0), (4, 0, 0)),
                Allocator.Persistent
            );
            var basePositions = new NativeArray<float3>(
                P((0, 0, 0), (1, 0, 0), (0, 0, 0)),
                Allocator.Persistent
            );
            var velocityPositions = new NativeArray<float3>(
                new float3[3],
                Allocator.Persistent
            );
            var friction = new NativeArray<float>(new float[3], Allocator.Persistent);
            var indices = new NativeArray<uint>(
                new[]
                {
                    DataUtility.Pack12_20(runtimeCase.Targets.Length, 0),
                    DataUtility.Pack12_20(0, runtimeCase.Targets.Length),
                    DataUtility.Pack12_20(0, runtimeCase.Targets.Length),
                },
                Allocator.Persistent
            );
            var targets = new NativeArray<ushort>(
                runtimeCase.Targets.Select(value => checked((ushort)value)).ToArray(),
                Allocator.Persistent
            );
            var rests = new NativeArray<float>(runtimeCase.RestSigned, Allocator.Persistent);
            try
            {
                object[] arguments =
                {
                    new DataChunk(0, 3),
                    new float4(0.0f, 1.0f, 0.0f, 0.0f),
                    team,
                    parameters,
                    attributes,
                    depths,
                    nextPositions,
                    basePositions,
                    velocityPositions,
                    friction,
                    indices,
                    targets,
                    rests,
                };
                try
                {
                    method.Invoke(null, arguments);
                }
                catch (TargetInvocationException exception) when (exception.InnerException != null)
                {
                    ExceptionDispatchInfo.Capture(exception.InnerException).Throw();
                    throw;
                }
                return new DistanceRuntimeDump
                {
                    NextPositions = nextPositions.ToArray(),
                    VelocityPositions = velocityPositions.ToArray(),
                };
            }
            finally
            {
                attributes.Dispose();
                depths.Dispose();
                nextPositions.Dispose();
                basePositions.Dispose();
                velocityPositions.Dispose();
                friction.Dispose();
                indices.Dispose();
                targets.Dispose();
                rests.Dispose();
            }
        }

        private static void BuildAdjacency(
            int[][] adjacency,
            out uint[] indexArray,
            out ushort[] dataArray
        )
        {
            indexArray = new uint[adjacency.Length];
            var data = new List<ushort>();
            for (int vertex = 0; vertex < adjacency.Length; vertex++)
            {
                int start = data.Count;
                foreach (int target in adjacency[vertex])
                {
                    data.Add(checked((ushort)target));
                }
                indexArray[vertex] = DataUtility.Pack12_20(adjacency[vertex].Length, start);
            }
            dataArray = data.ToArray();
        }

        private static void InvokePrivate(VirtualMesh mesh, string methodName)
        {
            MethodInfo method = typeof(VirtualMesh).GetMethod(
                methodName,
                BindingFlags.Instance | BindingFlags.NonPublic
            );
            if (method == null)
            {
                throw new MissingMethodException(typeof(VirtualMesh).FullName, methodName);
            }

            try
            {
                method.Invoke(mesh, null);
            }
            catch (TargetInvocationException exception) when (exception.InnerException != null)
            {
                ExceptionDispatchInfo.Capture(exception.InnerException).Throw();
                throw;
            }
        }

        private static OracleDump ReadDump(VirtualMesh mesh)
        {
            VertexAttribute[] attributes = mesh.attributes.ToArray();
            uint[] childIndices = NativeArrayOrEmpty(mesh.vertexChildIndexArray);
            ushort[] childData = NativeArrayOrEmpty(mesh.vertexChildDataArray);
            ushort[] baselineStarts = NativeArrayOrEmpty(mesh.baseLineStartDataIndices);
            ushort[] baselineCounts = NativeArrayOrEmpty(mesh.baseLineDataCounts);
            ExBitFlag8[] baselineFlags = NativeArrayOrEmpty(mesh.baseLineFlags);
            quaternion[] localRotations = NativeArrayOrEmpty(mesh.vertexLocalRotations);

            var childRanges = new int2[childIndices.Length];
            for (int index = 0; index < childIndices.Length; index++)
            {
                DataUtility.Unpack12_20(childIndices[index], out int count, out int start);
                childRanges[index] = new int2(start, count);
            }

            int baselineRangeCount = Math.Min(baselineStarts.Length, baselineCounts.Length);
            var baselineRanges = new int2[baselineRangeCount];
            for (int index = 0; index < baselineRangeCount; index++)
            {
                baselineRanges[index] = new int2(baselineStarts[index], baselineCounts[index]);
            }

            return new OracleDump
            {
                FinalAttributes = attributes.Select(value => value.Value).ToArray(),
                Parents = NativeArrayOrEmpty(mesh.vertexParentIndices),
                ChildRanges = childRanges,
                ChildData = childData.Select(value => (int)value).ToArray(),
                BaselineFlags = baselineFlags.Select(value => value.Value).ToArray(),
                BaselineRanges = baselineRanges,
                BaselineData = NativeArrayOrEmpty(mesh.baseLineData).Select(value => (int)value).ToArray(),
                Roots = NativeArrayOrEmpty(mesh.vertexRootIndices),
                Depths = NativeArrayOrEmpty(mesh.vertexDepths),
                LocalPositions = NativeArrayOrEmpty(mesh.vertexLocalPositions),
                LocalRotations = localRotations.Select(value => value.value).ToArray(),
            };
        }

        private static ProxyDump ReadProxyDump(VirtualMesh mesh)
        {
            uint[] vertexToVertexIndices = NativeArrayOrEmpty(mesh.vertexToVertexIndexArray);
            ushort[] vertexToVertexData = NativeArrayOrEmpty(mesh.vertexToVertexDataArray);
            var vertexToVertexRanges = new int2[vertexToVertexIndices.Length];
            for (int index = 0; index < vertexToVertexIndices.Length; index++)
            {
                DataUtility.Unpack12_20(vertexToVertexIndices[index], out int count, out int start);
                vertexToVertexRanges[index] = new int2(start, count);
            }

            FixedList32Bytes<uint>[] rawVertexToTriangles =
                NativeArrayOrEmpty(mesh.vertexToTriangles);
            var vertexToTriangleRecords = new int2[rawVertexToTriangles.Length][];
            for (int vertex = 0; vertex < rawVertexToTriangles.Length; vertex++)
            {
                FixedList32Bytes<uint> records = rawVertexToTriangles[vertex];
                var decoded = new int2[records.Length];
                for (int index = 0; index < records.Length; index++)
                {
                    uint packed = records[index];
                    decoded[index] = new int2(
                        DataUtility.Unpack12_20Hi(packed),
                        DataUtility.Unpack12_20Low(packed)
                    );
                }
                vertexToTriangleRecords[vertex] = decoded;
            }

            quaternion[] bindPoseRotations = NativeArrayOrEmpty(mesh.vertexBindPoseRotations);
            return new ProxyDump
            {
                FinalAttributes = mesh.attributes.ToArray().Select(value => value.Value).ToArray(),
                Triangles = mesh.triangles.ToArray(),
                Edges = CanonicalEdges(NativeArrayOrEmpty(mesh.edges)),
                VertexToVertexRanges = vertexToVertexRanges,
                VertexToVertexData = vertexToVertexData.Select(value => (int)value).ToArray(),
                VertexToTriangleRecords = vertexToTriangleRecords,
                LocalNormals = mesh.localNormals.ToArray(),
                LocalTangents = mesh.localTangents.ToArray(),
                VertexBindPosePositions = NativeArrayOrEmpty(mesh.vertexBindPosePositions),
                VertexBindPoseRotations = bindPoseRotations.Select(value => value.value).ToArray(),
            };
        }

        private static T[] NativeArrayOrEmpty<T>(NativeArray<T> values) where T : unmanaged
        {
            return values.IsCreated ? values.ToArray() : Array.Empty<T>();
        }

        private static IEnumerable<OracleCase> Cases()
        {
            yield return new OracleCase
            {
                Id = "mesh_baseline_single_fixed_triangle_001",
                Positions = P((0, 0, 0), (1, 0, 0), (0, 1, 0)),
                Attributes = new byte[] { 0x81, 0x82, 0x82 },
                Edges = E((0, 1), (0, 2), (1, 2)),
                Triangles = T((0, 1, 2)),
                Adjacency = A(new[] { 1, 2 }, new[] { 0, 2 }, new[] { 0, 1 }),
                Note = "Single fixed triangle and source parent-local orientation basis.",
            };
            yield return new OracleCase
            {
                Id = "mesh_baseline_no_fixed_001",
                Positions = P((0, 0, 0), (1, 0, 0), (0, 1, 0)),
                Attributes = new byte[] { 0x82, 0x82, 0x82 },
                Edges = E((0, 1), (0, 2), (1, 2)),
                Triangles = T((0, 1, 2)),
                Adjacency = A(new[] { 1, 2 }, new[] { 0, 2 }, new[] { 0, 1 }),
                Note = "No Fixed vertex; baseline pose arrays remain clear-memory initialized.",
            };
            yield return new OracleCase
            {
                Id = "mesh_baseline_disconnected_island_001",
                Positions = P((0, 0, 0), (1, 0, 0), (3, 0, 0), (4, 0, 0)),
                Attributes = new byte[] { 0x01, 0x02, 0x02, 0x02 },
                Edges = E((0, 1), (2, 3)),
                Triangles = Array.Empty<int3>(),
                Adjacency = A(new[] { 1 }, new[] { 0 }, new[] { 3 }, new[] { 2 }),
                Note = "Move-only disconnected island is not assigned to a baseline.",
            };
            yield return new OracleCase
            {
                Id = "mesh_baseline_multi_fixed_distance_001",
                Positions = P((0, 0, 0), (3, 0, 0), (1, 0, 0)),
                Attributes = new byte[] { 0x01, 0x01, 0x02 },
                Edges = E((0, 2), (1, 2)),
                Triangles = Array.Empty<int3>(),
                Adjacency = A(new[] { 2 }, new[] { 2 }, new[] { 0, 1 }),
                Note = "Move vertex selects the closer Fixed parent.",
            };
            yield return new OracleCase
            {
                Id = "mesh_baseline_move_angle_001",
                Positions = P((0, 0, 0), (1, 0, 0), (0, 1.5f, 0), (2, 0.1f, 0)),
                Attributes = new byte[] { 0x01, 0x02, 0x02, 0x02 },
                Edges = E((0, 1), (0, 2), (1, 3), (2, 3)),
                Triangles = Array.Empty<int3>(),
                Adjacency = A(new[] { 1, 2 }, new[] { 0, 3 }, new[] { 0, 3 }, new[] { 1, 2 }),
                Note = "Second wave selects the Move parent with the shallower continuation angle.",
            };
            yield return new OracleCase
            {
                Id = "mesh_baseline_same_frontier_parent_001",
                Positions = P((0, 0, 0), (1, 0, 0), (2, 0, 0)),
                Attributes = new byte[] { 0x01, 0x02, 0x02 },
                Edges = E((0, 1), (0, 2), (1, 2)),
                Triangles = Array.Empty<int3>(),
                Adjacency = A(new[] { 1, 2 }, new[] { 0, 2 }, new[] { 0, 1 }),
                Note = "Earlier Move in one sorted frontier can parent a later Move immediately.",
            };
            yield return new OracleCase
            {
                Id = "mesh_baseline_zero_distance_001",
                Positions = P((0, 0, 0), (0, 0, 0)),
                Attributes = new byte[] { 0x01, 0x02 },
                Edges = E((0, 1)),
                Triangles = Array.Empty<int3>(),
                Adjacency = A(new[] { 1 }, new[] { 0 }),
                Note = "Zero parent-local distance finalizes VertexAttribute.ZeroDistance.",
            };
            yield return new OracleCase
            {
                Id = "mesh_baseline_equal_cost_low_first_001",
                Positions = P((-1, 0, 0), (1, 0, 0), (0, 0, 0)),
                Attributes = new byte[] { 0x01, 0x01, 0x02 },
                Edges = E((0, 2), (1, 2)),
                Triangles = Array.Empty<int3>(),
                Adjacency = A(new[] { 2 }, new[] { 2 }, new[] { 0, 1 }),
                Note = "Equal Fixed cost with lower vertex index enumerated first.",
            };
            yield return new OracleCase
            {
                Id = "mesh_baseline_equal_cost_high_first_001",
                Positions = P((-1, 0, 0), (1, 0, 0), (0, 0, 0)),
                Attributes = new byte[] { 0x01, 0x01, 0x02 },
                Edges = E((0, 2), (1, 2)),
                Triangles = Array.Empty<int3>(),
                Adjacency = A(new[] { 2 }, new[] { 2 }, new[] { 1, 0 }),
                CompareToHoTools = false,
                Note = "Equal Fixed cost with higher vertex index enumerated first; source keeps first enumerated.",
            };
        }

        private static IEnumerable<ProxyCase> ProxyCases()
        {
            yield return new ProxyCase
            {
                Id = "mesh_proxy_consistent_winding_001",
                Positions = P((0, 0, 0), (1, 0, 0), (0, 1, 0)),
                Normals = Fill3(3, (0, 0, 1)),
                Tangents = Fill3(3, (1, 0, 0)),
                Uvs = UV((0, 0), (1, 0), (0, 1)),
                Attributes = new byte[] { 0x01, 0x02, 0x02 },
                Triangles = T((0, 1, 2)),
                Note = "Single triangle keeps winding and ORs Triangle bit into Fixed/Move attributes.",
            };
            yield return new ProxyCase
            {
                Id = "mesh_proxy_reversed_neighbor_001",
                Positions = P((0, 0, 0), (1, 0, 0), (0, 1, 0), (1, 1, 0)),
                Normals = Fill3(4, (0, 0, 1)),
                Tangents = Fill3(4, (1, 0, 0)),
                Uvs = UV((0, 0), (1, 0), (0, 1), (1, 1)),
                Attributes = new byte[] { 0x02, 0x02, 0x02, 0x02 },
                Triangles = T((0, 1, 2), (1, 2, 3)),
                Note = "Neighbor triangle starts reversed across a shared edge and is normalized by OptimizeTriangleDirection.",
            };
            yield return new ProxyCase
            {
                Id = "mesh_proxy_layer_boundary_001",
                Positions = P((0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 1, 1)),
                Normals = Fill3(4, (0, 0, 1)),
                Tangents = Fill3(4, (1, 0, 0)),
                Uvs = UV((0, 0), (1, 0), (0, 1), (1, 1)),
                Attributes = new byte[] { 0x02, 0x02, 0x02, 0x02 },
                Triangles = T((0, 1, 2), (1, 2, 3)),
                Note = "Shared-edge triangles above SameSurfaceAngle remain separate direction layers.",
            };
            yield return new ProxyCase
            {
                Id = "mesh_proxy_uv_tangent_001",
                Positions = P((0, 0, 0), (1, 0, 0), (0, 1, 0)),
                Normals = Fill3(3, (0, 0, 1)),
                Tangents = Fill3(3, (1, 0, 0)),
                Uvs = UV((0, 0), (1, 1), (0, 1)),
                Attributes = new byte[] { 0x02, 0x02, 0x02 },
                Triangles = T((0, 1, 2)),
                Note = "Triangle tangent is generated from final positions and per-vertex UVs.",
            };
            yield return new ProxyCase
            {
                Id = "mesh_proxy_uv_zero_area_001",
                Positions = P((0, 0, 0), (1, 0, 0), (0, 1, 0)),
                Normals = Fill3(3, (0, 0, 1)),
                Tangents = Fill3(3, (1, 0, 0)),
                Uvs = UV((0, 0), (1, 1), (2, 2)),
                Attributes = new byte[] { 0x02, 0x02, 0x02 },
                Triangles = T((0, 1, 2)),
                Note = "Zero UV area follows MathUtility.TriangleTangent area fallback without topology changes.",
            };
            yield return new ProxyCase
            {
                Id = "mesh_proxy_vertex_triangle_cap_001",
                Positions = P(
                    (0, 0, 0),
                    (1, 0, 0),
                    (0.7071068f, 0.7071068f, 0),
                    (0, 1, 0),
                    (-0.7071068f, 0.7071068f, 0),
                    (-1, 0, 0),
                    (-0.7071068f, -0.7071068f, 0),
                    (0, -1, 0),
                    (0.7071068f, -0.7071068f, 0)
                ),
                Normals = Fill3(9, (0, 0, 1)),
                Tangents = Fill3(9, (1, 0, 0)),
                Uvs = UV(
                    (0, 0),
                    (1, 0),
                    (0.7071068f, 0.7071068f),
                    (0, 1),
                    (-0.7071068f, 0.7071068f),
                    (-1, 0),
                    (-0.7071068f, -0.7071068f),
                    (0, -1),
                    (0.7071068f, -0.7071068f)
                ),
                Attributes = new byte[] { 0x02, 0x02, 0x02, 0x02, 0x02, 0x02, 0x02, 0x02, 0x02 },
                Triangles = T(
                    (0, 1, 2),
                    (0, 2, 3),
                    (0, 3, 4),
                    (0, 4, 5),
                    (0, 5, 6),
                    (0, 6, 7),
                    (0, 7, 8),
                    (0, 8, 1)
                ),
                Note = "A vertex touched by eight triangles keeps only seven vertexToTriangles records.",
            };
            yield return new ProxyCase
            {
                Id = "mesh_proxy_triangle_loose_line_001",
                Positions = P((0, 0, 0), (1, 0, 0), (0, 1, 0), (2, 0, 0), (3, 0, 0)),
                Normals = Fill3(5, (0, 0, 1)),
                Tangents = Fill3(5, (1, 0, 0)),
                Uvs = UV((0, 0), (1, 0), (0, 1), (2, 0), (3, 0)),
                Attributes = new byte[] { 0x01, 0x02, 0x02, 0x02, 0x02 },
                Lines = E((3, 4)),
                Triangles = T((0, 1, 2)),
                Note = "Explicit line edge is unioned with triangle edges while line-only vertices keep no Triangle bit.",
            };
            yield return new ProxyCase
            {
                Id = "mesh_proxy_attribute_or_001",
                Positions = P((0, 0, 0), (1, 0, 0), (0, 1, 0)),
                Normals = Fill3(3, (0, 0, 1)),
                Tangents = Fill3(3, (1, 0, 0)),
                Uvs = UV((0, 0), (1, 0), (0, 1)),
                Attributes = new byte[] { 0x11, 0x12, 0x02 },
                Triangles = T((0, 1, 2)),
                Note = "Triangle membership OR preserves Fixed/Move and DisableCollision bits.",
            };
        }

        private static IEnumerable<DistanceCase> DistanceCases()
        {
            yield return new DistanceCase
            {
                Id = "distance_parent_horizontal_001",
                Positions = P((0, 0, 0), (1, 0, 0), (0, 1, 0)),
                Attributes = new byte[] { 0x01, 0x02, 0x02 },
                Parents = new[] { -1, 0, 0 },
                Edges = E((0, 1), (0, 2), (1, 2)),
                Triangles = Array.Empty<int3>(),
                Adjacency = A(new[] { 1, 2 }, new[] { 0, 2 }, new[] { 0, 1 }),
                Note = "Parent edges are vertical positive rest; the sibling edge is horizontal negative rest.",
            };
            yield return new DistanceCase
            {
                Id = "distance_square_shear_001",
                Positions = P((0, 0, 0), (1, 0, 0), (0, 1, 0), (1, 1, 0)),
                Attributes = new byte[] { 0x01, 0x02, 0x02, 0x02 },
                Parents = new[] { -1, 0, 0, 1 },
                Edges = E((0, 1), (0, 2), (1, 2), (1, 3), (2, 3)),
                Triangles = T((0, 1, 2), (1, 3, 2)),
                Adjacency = A(
                    new[] { 1, 2 },
                    new[] { 0, 2, 3 },
                    new[] { 0, 1, 3 },
                    new[] { 1, 2 }
                ),
                Note = "Coplanar square adds the missing opposite diagonal 0-3 as bidirectional horizontal shear.",
            };
            yield return new DistanceCase
            {
                Id = "distance_shear_normal_reject_001",
                Positions = P((0, 0, 0), (1, 0, 0), (0, 1, 0), (1, 0, 1)),
                Attributes = new byte[] { 0x01, 0x02, 0x02, 0x02 },
                Parents = new[] { -1, 0, 0, 1 },
                Edges = E((0, 1), (0, 2), (1, 2), (1, 3), (2, 3)),
                Triangles = T((0, 1, 2), (1, 3, 2)),
                Adjacency = A(
                    new[] { 1, 2 },
                    new[] { 0, 2, 3 },
                    new[] { 0, 1, 3 },
                    new[] { 1, 2 }
                ),
                Note = "A folded triangle pair fails the abs(normal dot) shear threshold.",
            };
            yield return new DistanceCase
            {
                Id = "distance_shear_ratio_reject_001",
                Positions = P((0, 0, 0), (1, 0, 0), (0, 1, 0), (3, 3, 0)),
                Attributes = new byte[] { 0x01, 0x02, 0x02, 0x02 },
                Parents = new[] { -1, 0, 0, 1 },
                Edges = E((0, 1), (0, 2), (1, 2), (1, 3), (2, 3)),
                Triangles = T((0, 1, 2), (1, 3, 2)),
                Adjacency = A(
                    new[] { 1, 2 },
                    new[] { 0, 2, 3 },
                    new[] { 0, 1, 3 },
                    new[] { 1, 2 }
                ),
                Note = "A coplanar pair with mismatched diagonals fails the 0.3 length-ratio threshold.",
            };
            yield return new DistanceCase
            {
                Id = "distance_invalid_filters_001",
                Positions = P((0, 0, 0), (1, 0, 0), (0, 1, 0), (1, 1, 0)),
                Attributes = new byte[] { 0x00, 0x02, 0x02, 0x02 },
                Parents = new[] { -1, -1, -1, -1 },
                Edges = E((0, 1), (0, 2), (1, 2), (1, 3), (2, 3)),
                Triangles = T((0, 1, 2), (1, 3, 2)),
                Adjacency = A(
                    new[] { 1, 2 },
                    new[] { 0, 2, 3 },
                    new[] { 0, 1, 3 },
                    new[] { 1, 2 }
                ),
                Note = "Ordinary edges touching Invalid vertex 0 are filtered, but shear 0-3 is still emitted.",
            };
            yield return new DistanceCase
            {
                Id = "distance_all_fixed_empty_001",
                Positions = P((0, 0, 0), (1, 0, 0)),
                Attributes = new byte[] { 0x01, 0x01 },
                Parents = new[] { -1, -1 },
                Edges = E((0, 1)),
                Triangles = Array.Empty<int3>(),
                Adjacency = A(new[] { 1 }, new[] { 0 }),
                Note = "An all-Fixed ordinary edge produces no Distance arrays.",
            };
            yield return new DistanceCase
            {
                Id = "distance_zero_kind_loss_001",
                Positions = P((0, 0, 0), (0, 0, 0), (0, 0, 0)),
                Attributes = new byte[] { 0x01, 0x02, 0x02 },
                Parents = new[] { -1, 0, 0 },
                Edges = E((0, 1), (0, 2), (1, 2)),
                Triangles = Array.Empty<int3>(),
                Adjacency = A(new[] { 1, 2 }, new[] { 0, 2 }, new[] { 0, 1 }),
                Note = "Vertical and horizontal distances below 1e-8 both serialize as positive zero.",
            };
        }

        private static IEnumerable<DistanceRuntimeCase> DistanceRuntimeCases()
        {
            yield return new DistanceRuntimeCase
            {
                Id = "distance_runtime_nonzero_then_zero_001",
                Targets = new[] { 1, 2 },
                RestSigned = new[] { 1.0f, 0.0f },
                Note = "A trailing zero-distance record overwrites the earlier nonzero correction before averaging.",
            };
            yield return new DistanceRuntimeCase
            {
                Id = "distance_runtime_zero_then_nonzero_001",
                Targets = new[] { 2, 1 },
                RestSigned = new[] { 0.0f, 1.0f },
                Note = "The same records in reverse order preserve the zero correction and then add nonzero correction.",
            };
        }

        private static float3[] P(params (float x, float y, float z)[] values)
        {
            return values.Select(value => new float3(value.x, value.y, value.z)).ToArray();
        }

        private static float3[] Fill3(int count, (float x, float y, float z) value)
        {
            return Enumerable.Repeat(new float3(value.x, value.y, value.z), count).ToArray();
        }

        private static float2[] UV(params (float x, float y)[] values)
        {
            return values.Select(value => new float2(value.x, value.y)).ToArray();
        }

        private static int2[] E(params (int x, int y)[] values)
        {
            return values.Select(value => new int2(value.x, value.y)).ToArray();
        }

        private static int3[] T(params (int x, int y, int z)[] values)
        {
            return values.Select(value => new int3(value.x, value.y, value.z)).ToArray();
        }

        private static int[][] A(params int[][] values)
        {
            return values;
        }

        private static int2[] CanonicalEdges(IEnumerable<int2> values)
        {
            return values
                .Select(value => value.x <= value.y ? value : new int2(value.y, value.x))
                .GroupBy(value => value.x.ToString(CultureInfo.InvariantCulture) + ":" + value.y.ToString(CultureInfo.InvariantCulture))
                .Select(group => group.First())
                .OrderBy(value => value.x)
                .ThenBy(value => value.y)
                .ToArray();
        }

        private static string BuildJson(OracleCase oracleCase, OracleDump dump)
        {
            var text = new StringBuilder();
            text.AppendLine("{");
            Property(text, 2, "schema_version", "1");
            Property(text, 2, "case_id", Quote(oracleCase.Id));
            Property(
                text,
                2,
                "source",
                SourceJson(
                    "Runtime/VirtualMesh/Function/VirtualMeshProxy.cs::CreateMeshBaseLine",
                    "Runtime/VirtualMesh/Function/VirtualMeshProxy.cs::CreateBaseLinePose",
                    "Runtime/VirtualMesh/Function/VirtualMeshProxy.cs::CreateVertexRootAndDepth"
                )
            );
            Property(text, 2, "scope", Quote(oracleCase.Note));
            Property(text, 2, "comparison", ComparisonJson(oracleCase));
            Property(text, 2, "input", InputJson(oracleCase));
            Property(text, 2, "expected", ExpectedJson(dump), false);
            text.AppendLine("}");
            return text.ToString();
        }

        private static string BuildProxyJson(ProxyCase proxyCase, ProxyDump dump)
        {
            var text = new StringBuilder();
            text.AppendLine("{");
            Property(text, 2, "schema_version", "1");
            Property(text, 2, "case_id", Quote(proxyCase.Id));
            Property(
                text,
                2,
                "source",
                SourceJson("Runtime/VirtualMesh/Function/VirtualMeshProxy.cs::ConvertProxyMesh")
            );
            Property(text, 2, "scope", Quote(proxyCase.Note));
            Property(text, 2, "comparison", ProxyComparisonJson());
            Property(text, 2, "input", ProxyInputJson(proxyCase));
            Property(text, 2, "expected", ProxyOnlyExpectedJson(dump), false);
            text.AppendLine("}");
            return text.ToString();
        }

        private static string BuildDistanceJson(DistanceCase distanceCase, DistanceDump dump)
        {
            var text = new StringBuilder();
            text.AppendLine("{");
            Property(text, 2, "schema_version", "1");
            Property(text, 2, "case_id", Quote(distanceCase.Id));
            Property(
                text,
                2,
                "source",
                SourceJson(
                    "Runtime/Cloth/Constraints/DistanceConstraint.cs::CreateData",
                    "Runtime/Utility/Data/DataUtility.cs::Pack12_20"
                )
            );
            Property(text, 2, "scope", Quote(distanceCase.Note));
            Property(text, 2, "comparison", DistanceComparisonJson());
            Property(text, 2, "input", DistanceInputJson(distanceCase));
            Property(text, 2, "expected", DistanceExpectedJson(dump), false);
            text.AppendLine("}");
            return text.ToString();
        }

        private static string BuildDistanceRuntimeJson(
            DistanceRuntimeCase runtimeCase,
            DistanceRuntimeDump dump
        )
        {
            var text = new StringBuilder();
            text.AppendLine("{");
            Property(text, 2, "schema_version", "1");
            Property(text, 2, "case_id", Quote(runtimeCase.Id));
            Property(
                text,
                2,
                "source",
                SourceJson("Runtime/Cloth/Constraints/DistanceConstraint.cs::SolverConstraint")
            );
            Property(text, 2, "scope", Quote(runtimeCase.Note));
            Property(text, 2, "comparison", DistanceRuntimeComparisonJson());
            Property(text, 2, "input", DistanceRuntimeInputJson(runtimeCase));
            Property(text, 2, "expected", DistanceRuntimeExpectedJson(dump), false);
            text.AppendLine("}");
            return text.ToString();
        }

        private static string SourceJson(params string[] producers)
        {
            var text = new StringBuilder();
            text.AppendLine("{");
            Property(text, 4, "repository", Quote("MagicaCloth2"));
            Property(text, 4, "version", Quote(MC2Version));
            Property(text, 4, "commit", Quote(MC2Commit));
            Property(text, 4, "oracle_tier", Quote("A"));
            Property(text, 4, "unity_editor", Quote(Application.unityVersion));
            Property(text, 4, "burst", Quote(PackageVersion(typeof(BurstCompiler).Assembly)));
            Property(text, 4, "collections", Quote(PackageVersion(typeof(NativeList<int>).Assembly)));
            Property(text, 4, "mathematics", Quote(PackageVersion(typeof(float3).Assembly)));
            Property(
                text,
                4,
                "producer",
                StringArray(producers),
                false
            );
            text.Append("  }");
            return text.ToString();
        }

        private static string ComparisonJson(OracleCase oracleCase)
        {
            var text = new StringBuilder();
            text.AppendLine("{");
            Property(text, 4, "float_abs_tolerance", "1e-6");
            Property(text, 4, "float_rel_tolerance", "1e-6");
            Property(
                text,
                4,
                "unordered_fields",
                StringArray(
                    "baseline.child_data siblings within one parent",
                    "baseline.baseline_data sibling traversal"
                )
            );
            Property(text, 4, "source_equal_cost_policy", Quote("first_enumerated"));
            Property(text, 4, "hotools_equal_cost_policy", Quote("lowest_vertex_index"));
            Property(text, 4, "compare_to_hotools", oracleCase.CompareToHoTools ? "true" : "false", false);
            text.Append("  }");
            return text.ToString();
        }

        private static string ProxyComparisonJson()
        {
            var text = new StringBuilder();
            text.AppendLine("{");
            Property(text, 4, "float_abs_tolerance", "1e-6");
            Property(text, 4, "float_rel_tolerance", "1e-6");
            Property(text, 4, "unordered_fields", StringArray("proxy.edges"));
            Property(
                text,
                4,
                "vertex_to_triangle_record",
                Quote("[flip_flag, triangle_index], DataUtility.Pack12_20 decoded"),
                false
            );
            text.Append("  }");
            return text.ToString();
        }

        private static string DistanceComparisonJson()
        {
            var text = new StringBuilder();
            text.AppendLine("{");
            Property(text, 4, "float_abs_tolerance", "1e-6");
            Property(text, 4, "float_rel_tolerance", "1e-6");
            Property(
                text,
                4,
                "raw_order",
                Quote("diagnostic: NativeParallelMultiHashMap sibling order")
            );
            Property(
                text,
                4,
                "canonical_static_membership",
                Quote("per source vertex: (rest-sign-class,target,rest), zero is a separate class"),
                false
            );
            text.Append("  }");
            return text.ToString();
        }

        private static string DistanceRuntimeComparisonJson()
        {
            var text = new StringBuilder();
            text.AppendLine("{");
            Property(text, 4, "float_abs_tolerance", "1e-6");
            Property(text, 4, "float_rel_tolerance", "1e-6");
            Property(text, 4, "record_order", Quote("ordered and numerically significant"), false);
            text.Append("  }");
            return text.ToString();
        }

        private static string InputJson(OracleCase oracleCase)
        {
            int count = oracleCase.Positions.Length;
            var text = new StringBuilder();
            text.AppendLine("{");
            Property(text, 4, "task_id", Quote("mc2:mesh_cloth:" + oracleCase.Id));
            Property(text, 4, "setup_type", Quote("mesh_cloth"));
            Property(
                text,
                4,
                "vertex_identities",
                StringArray(Enumerable.Range(0, count).Select(index => "mesh:v" + index).ToArray())
            );
            Property(text, 4, "local_positions", ArrayJson(oracleCase.Positions, Vector3Json));
            Property(
                text,
                4,
                "local_normals",
                ArrayJson(Enumerable.Repeat(new float3(0, 0, 1), count), Vector3Json)
            );
            Property(
                text,
                4,
                "local_tangents",
                ArrayJson(Enumerable.Repeat(new float3(1, 0, 0), count), Vector3Json)
            );
            Property(
                text,
                4,
                "uvs",
                ArrayJson(Enumerable.Repeat(new float2(0, 0), count), Vector2Json)
            );
            Property(text, 4, "vertex_attributes", NumberArray(oracleCase.Attributes.Select(value => (int)value)));
            Property(text, 4, "edges", ArrayJson(oracleCase.Edges, Int2Json));
            Property(text, 4, "triangles", ArrayJson(oracleCase.Triangles, Int3Json));
            Property(
                text,
                4,
                "source_adjacency",
                ArrayJson(oracleCase.Adjacency, values => NumberArray(values)),
                false
            );
            text.Append("  }");
            return text.ToString();
        }

        private static string ProxyInputJson(ProxyCase proxyCase)
        {
            int count = proxyCase.Positions.Length;
            var text = new StringBuilder();
            text.AppendLine("{");
            Property(text, 4, "task_id", Quote("mc2:mesh_cloth:" + proxyCase.Id));
            Property(text, 4, "setup_type", Quote("mesh_cloth"));
            Property(
                text,
                4,
                "vertex_identities",
                StringArray(Enumerable.Range(0, count).Select(index => "mesh:v" + index).ToArray())
            );
            Property(text, 4, "local_positions", ArrayJson(proxyCase.Positions, Vector3Json));
            Property(text, 4, "local_normals", ArrayJson(proxyCase.Normals, Vector3Json));
            Property(text, 4, "local_tangents", ArrayJson(proxyCase.Tangents, Vector3Json));
            Property(text, 4, "uvs", ArrayJson(proxyCase.Uvs, Vector2Json));
            Property(text, 4, "vertex_attributes", NumberArray(proxyCase.Attributes.Select(value => (int)value)));
            Property(text, 4, "lines", ArrayJson(proxyCase.Lines, Int2Json));
            Property(text, 4, "triangles", ArrayJson(proxyCase.Triangles, Int3Json), false);
            text.Append("  }");
            return text.ToString();
        }

        private static string DistanceInputJson(DistanceCase distanceCase)
        {
            var text = new StringBuilder();
            text.AppendLine("{");
            Property(text, 4, "setup_type", Quote("mesh_cloth"));
            Property(text, 4, "local_positions", ArrayJson(distanceCase.Positions, Vector3Json));
            Property(
                text,
                4,
                "vertex_attributes",
                NumberArray(distanceCase.Attributes.Select(value => (int)value))
            );
            Property(text, 4, "parent_indices", NumberArray(distanceCase.Parents));
            Property(text, 4, "edges", ArrayJson(distanceCase.Edges, Int2Json));
            Property(text, 4, "triangles", ArrayJson(distanceCase.Triangles, Int3Json));
            Property(
                text,
                4,
                "vertex_to_vertex",
                ArrayJson(distanceCase.Adjacency, values => NumberArray(values)),
                false
            );
            text.Append("  }");
            return text.ToString();
        }

        private static string DistanceRuntimeInputJson(DistanceRuntimeCase runtimeCase)
        {
            var text = new StringBuilder();
            text.AppendLine("{");
            Property(text, 4, "setup_type", Quote("mesh_cloth"));
            Property(text, 4, "source_vertex", "0");
            Property(text, 4, "distance_targets", NumberArray(runtimeCase.Targets));
            Property(text, 4, "distance_rest_signed", ArrayJson(runtimeCase.RestSigned, FloatJson));
            Property(text, 4, "next_positions", ArrayJson(P((0, 0, 0), (2, 0, 0), (4, 0, 0)), Vector3Json));
            Property(text, 4, "base_positions", ArrayJson(P((0, 0, 0), (1, 0, 0), (0, 0, 0)), Vector3Json));
            Property(text, 4, "depths", ArrayJson(new[] { 0.5f, 0.0f, 0.0f }, FloatJson));
            Property(text, 4, "friction", ArrayJson(new[] { 0.0f, 0.0f, 0.0f }, FloatJson));
            Property(text, 4, "animation_pose_ratio", "0");
            Property(text, 4, "init_scale", "1");
            Property(text, 4, "scale_ratio", "1");
            Property(text, 4, "simulation_power_y", "1", false);
            text.Append("  }");
            return text.ToString();
        }

        private static string ExpectedJson(OracleDump dump)
        {
            var text = new StringBuilder();
            text.AppendLine("{");
            Property(text, 4, "proxy", ProxyExpectedJson(dump));
            Property(text, 4, "baseline", BaselineExpectedJson(dump), false);
            text.Append("  }");
            return text.ToString();
        }

        private static string ProxyOnlyExpectedJson(ProxyDump dump)
        {
            var text = new StringBuilder();
            text.AppendLine("{");
            Property(text, 4, "proxy", ProxyFinalJson(dump), false);
            text.Append("  }");
            return text.ToString();
        }

        private static string ProxyExpectedJson(OracleDump dump)
        {
            var text = new StringBuilder();
            text.AppendLine("{");
            Property(
                text,
                6,
                "vertex_attributes",
                NumberArray(dump.FinalAttributes.Select(value => (int)value)),
                false
            );
            text.Append("    }");
            return text.ToString();
        }

        private static string ProxyFinalJson(ProxyDump dump)
        {
            var text = new StringBuilder();
            text.AppendLine("{");
            Property(text, 6, "vertex_attributes", NumberArray(dump.FinalAttributes.Select(value => (int)value)));
            Property(text, 6, "triangles", ArrayJson(dump.Triangles, Int3Json));
            Property(text, 6, "edges", ArrayJson(dump.Edges, Int2Json));
            Property(text, 6, "vertex_to_vertex_ranges", ArrayJson(dump.VertexToVertexRanges, Int2Json));
            Property(text, 6, "vertex_to_vertex_data", NumberArray(dump.VertexToVertexData));
            Property(
                text,
                6,
                "vertex_to_triangle_records",
                ArrayJson(dump.VertexToTriangleRecords, records => ArrayJson(records, Int2Json))
            );
            Property(text, 6, "local_normals", ArrayJson(dump.LocalNormals, Vector3Json));
            Property(text, 6, "local_tangents", ArrayJson(dump.LocalTangents, Vector3Json));
            Property(text, 6, "vertex_bind_pose_positions", ArrayJson(dump.VertexBindPosePositions, Vector3Json));
            Property(
                text,
                6,
                "vertex_bind_pose_rotations",
                ArrayJson(dump.VertexBindPoseRotations, Vector4Json),
                false
            );
            text.Append("    }");
            return text.ToString();
        }

        private static string BaselineExpectedJson(OracleDump dump)
        {
            var text = new StringBuilder();
            text.AppendLine("{");
            Property(text, 6, "parent_indices", NumberArray(dump.Parents));
            Property(text, 6, "child_ranges", ArrayJson(dump.ChildRanges, Int2Json));
            Property(text, 6, "child_data", NumberArray(dump.ChildData));
            Property(text, 6, "baseline_flags", NumberArray(dump.BaselineFlags.Select(value => (int)value)));
            Property(text, 6, "baseline_ranges", ArrayJson(dump.BaselineRanges, Int2Json));
            Property(text, 6, "baseline_data", NumberArray(dump.BaselineData));
            Property(text, 6, "root_indices", NumberArray(dump.Roots));
            Property(text, 6, "depths", ArrayJson(dump.Depths, FloatJson));
            Property(text, 6, "vertex_local_positions", ArrayJson(dump.LocalPositions, Vector3Json));
            Property(text, 6, "vertex_local_rotations", ArrayJson(dump.LocalRotations, Vector4Json), false);
            text.Append("    }");
            return text.ToString();
        }

        private static string DistanceExpectedJson(DistanceDump dump)
        {
            var text = new StringBuilder();
            text.AppendLine("{");
            Property(text, 4, "raw_packed_indices", UIntArray(dump.PackedIndices));
            Property(text, 4, "distance_ranges", ArrayJson(dump.Ranges, Int2Json));
            Property(text, 4, "distance_targets", NumberArray(dump.Targets));
            Property(
                text,
                4,
                "distance_rest_signed",
                ArrayJson(dump.RestSigned, FloatJson),
                false
            );
            text.Append("  }");
            return text.ToString();
        }

        private static string DistanceRuntimeExpectedJson(DistanceRuntimeDump dump)
        {
            var text = new StringBuilder();
            text.AppendLine("{");
            Property(text, 4, "next_positions", ArrayJson(dump.NextPositions, Vector3Json));
            Property(
                text,
                4,
                "velocity_positions",
                ArrayJson(dump.VelocityPositions, Vector3Json),
                false
            );
            text.Append("  }");
            return text.ToString();
        }

        private static string PackageVersion(Assembly assembly)
        {
            UnityEditor.PackageManager.PackageInfo info =
                UnityEditor.PackageManager.PackageInfo.FindForAssembly(assembly);
            return info != null ? info.version : "unknown";
        }

        private static string CommandLineValue(string name)
        {
            string[] arguments = Environment.GetCommandLineArgs();
            for (int index = 0; index + 1 < arguments.Length; index++)
            {
                if (string.Equals(arguments[index], name, StringComparison.Ordinal))
                {
                    return arguments[index + 1];
                }
            }
            return string.Empty;
        }

        private static void Property(
            StringBuilder text,
            int indent,
            string name,
            string json,
            bool comma = true
        )
        {
            text.Append(' ', indent).Append(Quote(name)).Append(": ").Append(json);
            if (comma)
            {
                text.Append(',');
            }
            text.AppendLine();
        }

        private static string Quote(string value)
        {
            if (value == null)
            {
                return "null";
            }
            var text = new StringBuilder("\"");
            foreach (char character in value)
            {
                switch (character)
                {
                    case '\\': text.Append("\\\\"); break;
                    case '"': text.Append("\\\""); break;
                    case '\n': text.Append("\\n"); break;
                    case '\r': text.Append("\\r"); break;
                    case '\t': text.Append("\\t"); break;
                    default: text.Append(character); break;
                }
            }
            return text.Append('"').ToString();
        }

        private static string StringArray(params string[] values)
        {
            return "[" + string.Join(",", values.Select(Quote)) + "]";
        }

        private static string NumberArray(IEnumerable<int> values)
        {
            return "[" + string.Join(",", values.Select(value => value.ToString(CultureInfo.InvariantCulture))) + "]";
        }

        private static string UIntArray(IEnumerable<uint> values)
        {
            return "[" + string.Join(",", values.Select(value => value.ToString(CultureInfo.InvariantCulture))) + "]";
        }

        private static string ArrayJson<T>(IEnumerable<T> values, Func<T, string> convert)
        {
            return "[" + string.Join(",", values.Select(convert)) + "]";
        }

        private static string FloatJson(float value)
        {
            if (float.IsNaN(value) || float.IsInfinity(value))
            {
                throw new InvalidDataException("Oracle output contains NaN/Inf");
            }
            return value.ToString("R", CultureInfo.InvariantCulture);
        }

        private static string Vector2Json(float2 value)
        {
            return $"[{FloatJson(value.x)},{FloatJson(value.y)}]";
        }

        private static string Vector3Json(float3 value)
        {
            return $"[{FloatJson(value.x)},{FloatJson(value.y)},{FloatJson(value.z)}]";
        }

        private static string Vector4Json(float4 value)
        {
            return $"[{FloatJson(value.x)},{FloatJson(value.y)},{FloatJson(value.z)},{FloatJson(value.w)}]";
        }

        private static string Int2Json(int2 value)
        {
            return $"[{value.x},{value.y}]";
        }

        private static string Int3Json(int3 value)
        {
            return $"[{value.x},{value.y},{value.z}]";
        }
    }
}
