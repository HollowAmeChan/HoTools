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
using Unity.Collections.LowLevel.Unsafe;
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

        private sealed class BendingCase
        {
            public string Id;
            public float3[] Positions;
            public byte[] Attributes;
            public int2[] Edges;
            public int3[] Triangles;
            public float4x4 InitLocalToWorld = float4x4.identity;
            public string Note = string.Empty;
        }

        private sealed class BendingDump
        {
            public bool CreateReturnedNull;
            public ulong[] RawPackedQuads;
            public int4[] OrderedQuads;
            public float[] RestAngleOrVolume;
            public int[] SignOrVolume;
            public int WriteBufferCount;
            public uint[] RawWriteData;
            public uint[] RawWriteIndices;
            public int2[] WriteRanges;
        }

        private sealed class BendingRuntimeCase
        {
            public string Id;
            public int4[] OrderedQuads;
            public float[] RestAngleOrVolume;
            public sbyte[] SignOrVolume;
            public float3[] NextPositions;
            public byte[] Attributes;
            public float ScaleRatio = 1.0f;
            public float NegativeScaleSign = 1.0f;
            public string Note = string.Empty;
        }

        private sealed class BendingRuntimeDump
        {
            public int[] CountBeforeSum;
            public int[] VectorComponentsBeforeSum;
            public float3[] NextPositionsAfterSum;
            public int[] CountAfterSum;
            public float3[] VectorAfterSum;
        }

        [Serializable]
        private sealed class ParameterRuntimeDump
        {
            public int abi_version = 0;
            public string[] float_fields =
            {
                "gravity",
                "gravity_direction_x", "gravity_direction_y", "gravity_direction_z",
                "gravity_falloff", "stabilization_time_after_reset", "blend_weight",
                "rotational_interpolation", "root_rotation",
                "distance_culling_length", "distance_culling_fade_ratio",
                "anchor_inertia", "world_inertia", "movement_inertia_smoothing",
                "movement_speed_limit", "rotation_speed_limit", "local_inertia",
                "local_movement_speed_limit", "local_rotation_speed_limit", "depth_inertia",
                "centrifugal_acceleration", "particle_speed_limit",
                "teleport_distance", "teleport_rotation",
                "tether_compression_limit", "tether_stretch_limit",
                "distance_velocity_attenuation", "bending_stiffness",
                "angle_restoration_velocity_attenuation", "angle_restoration_gravity_falloff",
                "angle_limit_stiffness", "backstop_radius", "motion_stiffness",
                "collision_dynamic_friction", "collision_static_friction", "cloth_mass",
                "wind_influence", "wind_frequency", "wind_turbulence", "wind_blend",
                "wind_synchronization", "wind_depth_weight", "moving_wind",
                "spring_power", "spring_limit_distance", "spring_normal_limit_ratio", "spring_noise",
            };
            public string[] int_fields =
            {
                "normal_axis", "use_distance_culling", "teleport_mode", "bending_method",
                "use_angle_restoration", "use_angle_limit", "use_max_distance", "use_backstop",
                "collision_mode", "self_collision_mode", "self_collision_sync_mode",
            };
            public string[] curve_fields =
            {
                "damping", "radius", "distance_stiffness", "angle_restoration_stiffness",
                "angle_limit", "max_distance", "backstop_distance", "collision_limit_distance",
                "self_collision_thickness",
            };
            public float[] float_values;
            public int[] int_values;
            public float[] curve_values;
            public int[] curve_shape = { 9, 16 };
        }

        [Serializable]
        private sealed class ParameterOracleOutput
        {
            public string case_id;
            public string oracle_tier = "A";
            public string mc2_version = MC2Version;
            public string mc2_commit = MC2Commit;
            public string source = "Runtime/Cloth/ClothSerializeDataFunction.cs::GetClothParameters";
            public string note;
            public ParameterRuntimeDump expected;
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

            int bendingWritten = 0;
            foreach (BendingCase bendingCase in BendingCases())
            {
                BendingDump dump = RunBendingCase(bendingCase);
                string json = BuildBendingJson(bendingCase, dump);
                string path = Path.Combine(outputDirectory, bendingCase.Id + ".json");
                File.WriteAllText(path, json, new UTF8Encoding(false));
                Debug.Log($"[MC2 Oracle] wrote {path}");
                bendingWritten++;
            }

            int bendingRuntimeWritten = 0;
            foreach (BendingRuntimeCase runtimeCase in BendingRuntimeCases())
            {
                BendingRuntimeDump dump = RunBendingRuntimeCase(runtimeCase);
                string json = BuildBendingRuntimeJson(runtimeCase, dump);
                string path = Path.Combine(outputDirectory, runtimeCase.Id + ".json");
                File.WriteAllText(path, json, new UTF8Encoding(false));
                Debug.Log($"[MC2 Oracle] wrote {path}");
                bendingRuntimeWritten++;
            }

            int parameterWritten = WriteParameterFixtures(outputDirectory);

            Debug.Log(
                $"[MC2 Oracle] PASS: {written} Tier A Mesh baseline fixtures, "
                + $"{proxyWritten} proxy fixtures, {distanceWritten} distance fixtures, "
                + $"{distanceRuntimeWritten} distance runtime fixtures, "
                + $"{bendingWritten} bending fixtures, "
                + $"{bendingRuntimeWritten} bending runtime fixtures, "
                + $"{parameterWritten} runtime parameter fixtures"
            );
        }

        private static int WriteParameterFixtures(string outputDirectory)
        {
            var mesh = new ClothSerializeData();
            SetHostProfileCurveDefaults(mesh);
            mesh.clothType = ClothProcess.ClothType.MeshCloth;
            mesh.gravityDirection = new float3(0.0f, 0.0f, -1.0f);
            mesh.damping = new CurveSerializeData(
                0.5f,
                new AnimationCurve(
                    new Keyframe(0.0f, 0.0f, 0.0f, 0.0f),
                    new Keyframe(0.5f, 1.0f, 0.0f, 0.0f),
                    new Keyframe(1.0f, 0.25f, 0.0f, 0.0f)
                )
            );
            WriteParameterFixture(
                outputDirectory,
                "runtime_parameters_mesh_curve_001",
                "MeshCloth curve sampling at i/15 plus ordinary conversion rules.",
                PackRuntimeParameters(mesh.GetClothParameters())
            );

            var spring = new ClothSerializeData();
            SetHostProfileCurveDefaults(spring);
            spring.clothType = ClothProcess.ClothType.BoneSpring;
            spring.gravity = 9.0f;
            spring.tetherConstraint.distanceCompression = 0.25f;
            spring.distanceConstraint.stiffness.SetValue(0.9f);
            spring.motionConstraint.useMaxDistance = true;
            spring.motionConstraint.useBackstop = true;
            spring.colliderCollisionConstraint.mode = ColliderCollisionConstraint.Mode.Edge;
            spring.colliderCollisionConstraint.friction = 0.1f;
            spring.colliderCollisionConstraint.limitDistance.SetValue(0.125f);
            spring.selfCollisionConstraint.selfMode = SelfCollisionConstraint.SelfCollisionMode.FullMesh;
            spring.selfCollisionConstraint.syncMode = SelfCollisionConstraint.SelfCollisionMode.FullMesh;
            spring.springConstraint.useSpring = true;
            spring.springConstraint.springPower = 0.3f;
            WriteParameterFixture(
                outputDirectory,
                "runtime_parameters_bone_spring_001",
                "BoneSpring fixed overrides from GetClothParameters().",
                PackRuntimeParameters(spring.GetClothParameters())
            );
            return 2;
        }

        private static void SetHostProfileCurveDefaults(ClothSerializeData value)
        {
            value.damping.SetValue(0.05f);
            value.radius.SetValue(0.02f);
            value.distanceConstraint.stiffness.SetValue(1.0f);
            value.angleRestorationConstraint.stiffness.SetValue(0.2f);
            value.angleLimitConstraint.limitAngle.SetValue(60.0f);
            value.motionConstraint.maxDistance.SetValue(0.3f);
            value.motionConstraint.backstopDistance.SetValue(0.0f);
            value.colliderCollisionConstraint.limitDistance.SetValue(0.05f);
            value.selfCollisionConstraint.surfaceThickness.SetValue(0.005f);
        }

        private static void WriteParameterFixture(
            string outputDirectory,
            string caseId,
            string note,
            ParameterRuntimeDump expected
        )
        {
            var output = new ParameterOracleOutput
            {
                case_id = caseId,
                note = note,
                expected = expected,
            };
            string path = Path.Combine(outputDirectory, caseId + ".json");
            File.WriteAllText(path, JsonUtility.ToJson(output, true), new UTF8Encoding(false));
            Debug.Log($"[MC2 Oracle] wrote {path}");
        }

        private static ParameterRuntimeDump PackRuntimeParameters(ClothParameters value)
        {
            var inertia = value.inertiaConstraint;
            var tether = value.tetherConstraint;
            var distance = value.distanceConstraint;
            var bending = value.triangleBendingConstraint;
            var angle = value.angleConstraint;
            var motion = value.motionConstraint;
            var collision = value.colliderCollisionConstraint;
            var selfCollision = value.selfCollisionConstraint;
            var wind = value.wind;
            var spring = value.springConstraint;
            return new ParameterRuntimeDump
            {
                float_values = new[]
                {
                    value.gravity,
                    value.worldGravityDirection.x, value.worldGravityDirection.y, value.worldGravityDirection.z,
                    value.gravityFalloff, value.stablizationTimeAfterReset, value.blendWeight,
                    value.rotationalInterpolation, value.rootRotation,
                    value.culling.distanceCullingLength, value.culling.distanceCullingFadeRatio,
                    inertia.anchorInertia, inertia.worldInertia, inertia.movementInertiaSmoothing,
                    inertia.movementSpeedLimit, inertia.rotationSpeedLimit, inertia.localInertia,
                    inertia.localMovementSpeedLimit, inertia.localRotationSpeedLimit, inertia.depthInertia,
                    inertia.centrifualAcceleration, inertia.particleSpeedLimit,
                    inertia.teleportDistance, inertia.teleportRotation,
                    tether.compressionLimit, tether.stretchLimit,
                    distance.velocityAttenuation, bending.stiffness,
                    angle.restorationVelocityAttenuation, angle.restorationGravityFalloff,
                    angle.limitstiffness, motion.backstopRadius, motion.stiffness,
                    collision.dynamicFriction, collision.staticFriction, selfCollision.clothMass,
                    wind.influence, wind.frequency, wind.turbulence, wind.blend,
                    wind.synchronization, wind.depthWeight, wind.movingWind,
                    spring.springPower, spring.limitDistance, spring.normalLimitRatio, spring.springNoise,
                },
                int_values = new[]
                {
                    (int)value.normalAxis,
                    value.culling.useDistanceCulling ? 1 : 0,
                    (int)inertia.teleportMode,
                    (int)bending.method,
                    angle.useAngleRestoration ? 1 : 0,
                    angle.useAngleLimit ? 1 : 0,
                    motion.useMaxDistance ? 1 : 0,
                    motion.useBackstop ? 1 : 0,
                    (int)collision.mode,
                    (int)selfCollision.selfMode,
                    (int)selfCollision.syncMode,
                },
                curve_values = new[]
                {
                    value.dampingCurveData,
                    value.radiusCurveData,
                    distance.restorationStiffness,
                    angle.restorationStiffness,
                    angle.limitCurveData,
                    motion.maxDistanceCurveData,
                    motion.backstopDistanceCurveData,
                    collision.limitDistance,
                    selfCollision.surfaceThicknessCurveData,
                }.SelectMany(MatrixValues).ToArray(),
            };
        }

        private static IEnumerable<float> MatrixValues(float4x4 value)
        {
            yield return value.c0.x; yield return value.c0.y; yield return value.c0.z; yield return value.c0.w;
            yield return value.c1.x; yield return value.c1.y; yield return value.c1.z; yield return value.c1.w;
            yield return value.c2.x; yield return value.c2.y; yield return value.c2.z; yield return value.c2.w;
            yield return value.c3.x; yield return value.c3.y; yield return value.c3.z; yield return value.c3.w;
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

        private static BendingDump RunBendingCase(BendingCase bendingCase)
        {
            using (var mesh = new VirtualMesh(bendingCase.Id))
            {
                mesh.localPositions = new ExSimpleNativeArray<float3>(bendingCase.Positions);
                mesh.attributes = new ExSimpleNativeArray<VertexAttribute>(
                    bendingCase.Attributes.Select(value => new VertexAttribute(value)).ToArray()
                );
                mesh.edges = new NativeArray<int2>(bendingCase.Edges, Allocator.Persistent);
                mesh.triangles = new ExSimpleNativeArray<int3>(bendingCase.Triangles);
                mesh.edgeToTriangles = BuildEdgeToTriangles(bendingCase.Triangles);
                mesh.initLocalToWorld = bendingCase.InitLocalToWorld;

                TriangleBendingConstraint.ConstraintData data =
                    TriangleBendingConstraint.CreateData(mesh, new ClothParameters());
                if (data == null)
                {
                    return new BendingDump
                    {
                        CreateReturnedNull = true,
                        RawPackedQuads = Array.Empty<ulong>(),
                        OrderedQuads = Array.Empty<int4>(),
                        RestAngleOrVolume = Array.Empty<float>(),
                        SignOrVolume = Array.Empty<int>(),
                        RawWriteData = Array.Empty<uint>(),
                        RawWriteIndices = Array.Empty<uint>(),
                        WriteRanges = Array.Empty<int2>(),
                    };
                }
                ulong[] packed = data.trianglePairArray ?? Array.Empty<ulong>();
                uint[] writeIndices = data.writeIndexArray ?? Array.Empty<uint>();
                var writeRanges = new int2[writeIndices.Length];
                for (int index = 0; index < writeIndices.Length; index++)
                {
                    DataUtility.Unpack12_20(writeIndices[index], out int count, out int start);
                    writeRanges[index] = new int2(start, count);
                }
                return new BendingDump
                {
                    CreateReturnedNull = false,
                    RawPackedQuads = packed,
                    OrderedQuads = packed.Select(value => DataUtility.Unpack64(value)).ToArray(),
                    RestAngleOrVolume = data.restAngleOrVolumeArray ?? Array.Empty<float>(),
                    SignOrVolume = (data.signOrVolumeArray ?? Array.Empty<sbyte>())
                        .Select(value => (int)value)
                        .ToArray(),
                    WriteBufferCount = data.writeBufferCount,
                    RawWriteData = data.writeDataArray ?? Array.Empty<uint>(),
                    RawWriteIndices = writeIndices,
                    WriteRanges = writeRanges,
                };
            }
        }

        private static BendingRuntimeDump RunBendingRuntimeCase(
            BendingRuntimeCase runtimeCase
        )
        {
            MethodInfo solver = typeof(TriangleBendingConstraint).GetMethod(
                "SolverConstraint",
                BindingFlags.Static | BindingFlags.NonPublic
            );
            MethodInfo sum = typeof(TriangleBendingConstraint).GetMethod(
                "SumConstraint",
                BindingFlags.Static | BindingFlags.NonPublic
            );
            if (solver == null || sum == null)
            {
                throw new MissingMethodException(
                    typeof(TriangleBendingConstraint).FullName,
                    solver == null ? "SolverConstraint" : "SumConstraint"
                );
            }
            int vertexCount = runtimeCase.NextPositions.Length;
            int recordCount = runtimeCase.OrderedQuads.Length;
            if (
                runtimeCase.Attributes.Length != vertexCount
                || runtimeCase.RestAngleOrVolume.Length != recordCount
                || runtimeCase.SignOrVolume.Length != recordCount
            )
            {
                throw new InvalidDataException($"Invalid bending runtime case shape: {runtimeCase.Id}");
            }
            var team = new TeamManager.TeamData
            {
                scaleRatio = runtimeCase.ScaleRatio,
                negativeScaleSign = runtimeCase.NegativeScaleSign,
                proxyCommonChunk = new DataChunk(0, vertexCount),
                particleChunk = new DataChunk(0, vertexCount),
                bendingPairChunk = new DataChunk(0, recordCount),
            };
            var parameters = new ClothParameters();
            parameters.triangleBendingConstraint.Convert(
                new TriangleBendingConstraint.SerializeData { stiffness = 1.0f }
            );
            var attributes = new NativeArray<VertexAttribute>(
                runtimeCase.Attributes.Select(value => new VertexAttribute(value)).ToArray(),
                Allocator.Persistent
            );
            var depths = new NativeArray<float>(
                Enumerable.Repeat(0.5f, vertexCount).ToArray(),
                Allocator.Persistent
            );
            var nextPositions = new NativeArray<float3>(
                runtimeCase.NextPositions,
                Allocator.Persistent
            );
            var friction = new NativeArray<float>(
                new float[vertexCount],
                Allocator.Persistent
            );
            var quads = new NativeArray<ulong>(
                runtimeCase.OrderedQuads.Select(value => DataUtility.Pack64(value)).ToArray(),
                Allocator.Persistent
            );
            var rests = new NativeArray<float>(
                runtimeCase.RestAngleOrVolume,
                Allocator.Persistent
            );
            var markers = new NativeArray<sbyte>(
                runtimeCase.SignOrVolume,
                Allocator.Persistent
            );
            var vectors = new NativeArray<float3>(vertexCount, Allocator.Persistent);
            var counts = new NativeArray<int>(vertexCount, Allocator.Persistent);
            try
            {
                InvokeStatic(
                    solver,
                    new object[]
                    {
                        new DataChunk(0, recordCount),
                        new float4(0.0f, 1.0f, 0.0f, 0.0f),
                        team,
                        parameters,
                        attributes,
                        depths,
                        nextPositions,
                        friction,
                        quads,
                        rests,
                        markers,
                        vectors,
                        counts,
                    }
                );
                int[] countBefore = counts.ToArray();
                int[] vectorBefore = vectors
                    .Reinterpret<int>(UnsafeUtility.SizeOf<float3>())
                    .ToArray();
                InvokeStatic(
                    sum,
                    new object[]
                    {
                        new DataChunk(0, vertexCount),
                        team,
                        parameters,
                        attributes,
                        nextPositions,
                        vectors,
                        counts,
                    }
                );
                return new BendingRuntimeDump
                {
                    CountBeforeSum = countBefore,
                    VectorComponentsBeforeSum = vectorBefore,
                    NextPositionsAfterSum = nextPositions.ToArray(),
                    CountAfterSum = counts.ToArray(),
                    VectorAfterSum = vectors.ToArray(),
                };
            }
            finally
            {
                attributes.Dispose();
                depths.Dispose();
                nextPositions.Dispose();
                friction.Dispose();
                quads.Dispose();
                rests.Dispose();
                markers.Dispose();
                vectors.Dispose();
                counts.Dispose();
            }
        }

        private static void InvokeStatic(MethodInfo method, object[] arguments)
        {
            try
            {
                method.Invoke(null, arguments);
            }
            catch (TargetInvocationException exception) when (exception.InnerException != null)
            {
                ExceptionDispatchInfo.Capture(exception.InnerException).Throw();
                throw;
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

        private static IEnumerable<BendingCase> BendingCases()
        {
            yield return new BendingCase
            {
                Id = "bending_flat_dihedral_001",
                Positions = FoldedPair(0.0f),
                Attributes = new byte[] { 0x02, 0x02, 0x02, 0x02 },
                Edges = E((0, 2), (0, 3), (1, 2), (1, 3), (2, 3)),
                Triangles = T((0, 2, 3), (1, 3, 2)),
                Note = "Flat pair emits one directional dihedral record and dir==0 maps to sign +1.",
            };
            yield return new BendingCase
            {
                Id = "bending_fold_100_double_001",
                Positions = FoldedPair(100.0f),
                Attributes = new byte[] { 0x02, 0x02, 0x02, 0x02 },
                Edges = E((0, 2), (0, 3), (1, 2), (1, 3), (2, 3)),
                Triangles = T((0, 2, 3), (1, 3, 2)),
                Note = "A 100 degree pair emits bending first and volume second for the same ordered quad.",
            };
            yield return new BendingCase
            {
                Id = "bending_fold_89_9_bending_only_001",
                Positions = FoldedPair(89.9f),
                Attributes = new byte[] { 0x02, 0x02, 0x02, 0x02 },
                Edges = E((0, 2), (0, 3), (1, 2), (1, 3), (2, 3)),
                Triangles = T((0, 2, 3), (1, 3, 2)),
                Note = "A pair below 90 degrees emits bending but not volume.",
            };
            yield return new BendingCase
            {
                Id = "bending_fold_119_9_double_001",
                Positions = FoldedPair(119.9f),
                Attributes = new byte[] { 0x02, 0x02, 0x02, 0x02 },
                Edges = E((0, 2), (0, 3), (1, 2), (1, 3), (2, 3)),
                Triangles = T((0, 2, 3), (1, 3, 2)),
                Note = "A pair below the strict 120 degree cutoff still emits bending and volume.",
            };
            yield return new BendingCase
            {
                Id = "bending_fold_120_1_volume_only_001",
                Positions = FoldedPair(120.1f),
                Attributes = new byte[] { 0x02, 0x02, 0x02, 0x02 },
                Edges = E((0, 2), (0, 3), (1, 2), (1, 3), (2, 3)),
                Triangles = T((0, 2, 3), (1, 3, 2)),
                Note = "A pair above the strict 120 degree cutoff emits only volume.",
            };
            yield return new BendingCase
            {
                Id = "bending_fold_130_volume_only_001",
                Positions = FoldedPair(130.0f),
                Attributes = new byte[] { 0x02, 0x02, 0x02, 0x02 },
                Edges = E((0, 2), (0, 3), (1, 2), (1, 3), (2, 3)),
                Triangles = T((0, 2, 3), (1, 3, 2)),
                Note = "A 130 degree pair is excluded from bending but retained as volume.",
            };
            yield return new BendingCase
            {
                Id = "bending_fold_178_9_volume_only_001",
                Positions = FoldedPair(178.9f),
                Attributes = new byte[] { 0x02, 0x02, 0x02, 0x02 },
                Edges = E((0, 2), (0, 3), (1, 2), (1, 3), (2, 3)),
                Triangles = T((0, 2, 3), (1, 3, 2)),
                Note = "A pair below the 179 degree inclusive maximum still emits volume.",
            };
            yield return new BendingCase
            {
                Id = "bending_fold_above_179_empty_001",
                Positions = FoldedPair(179.5f),
                Attributes = new byte[] { 0x02, 0x02, 0x02, 0x02 },
                Edges = E((0, 2), (0, 3), (1, 2), (1, 3), (2, 3)),
                Triangles = T((0, 2, 3), (1, 3, 2)),
                Note = "An angle above 179 degrees is excluded from both bending and volume.",
            };
            yield return new BendingCase
            {
                Id = "bending_all_fixed_empty_001",
                Positions = FoldedPair(0.0f),
                Attributes = new byte[] { 0x01, 0x01, 0x01, 0x01 },
                Edges = E((0, 2), (0, 3), (1, 2), (1, 3), (2, 3)),
                Triangles = T((0, 2, 3), (1, 3, 2)),
                Note = "A four-Fixed pair returns success with empty main arrays.",
            };
            yield return new BendingCase
            {
                Id = "bending_invalid_empty_001",
                Positions = FoldedPair(0.0f),
                Attributes = new byte[] { 0x00, 0x02, 0x02, 0x02 },
                Edges = E((0, 2), (0, 3), (1, 2), (1, 3), (2, 3)),
                Triangles = T((0, 2, 3), (1, 3, 2)),
                Note = "Any Invalid vertex filters the complete quad.",
            };
            yield return new BendingCase
            {
                Id = "bending_fold_100_scaled_world_001",
                Positions = FoldedPair(100.0f),
                Attributes = new byte[] { 0x02, 0x02, 0x02, 0x02 },
                Edges = E((0, 2), (0, 3), (1, 2), (1, 3), (2, 3)),
                Triangles = T((0, 2, 3), (1, 3, 2)),
                InitLocalToWorld = float4x4.Scale(new float3(2.0f)),
                Note = "Uniform initial world scale leaves angle unchanged and scales signed volume by eight.",
            };
            yield return new BendingCase
            {
                Id = "bending_tetra_volume_first_wins_001",
                Positions = P((1, 1, 1), (-1, -1, 1), (-1, 1, -1), (1, -1, -1)),
                Attributes = new byte[] { 0x02, 0x02, 0x02, 0x02 },
                Edges = E((0, 1), (0, 2), (0, 3), (1, 2), (1, 3), (2, 3)),
                Triangles = T((0, 2, 1), (0, 1, 3), (0, 3, 2), (1, 2, 3)),
                Note = "Multiple edge roles share one unordered four-vertex volume key; only the first volume survives.",
            };
            yield return new BendingCase
            {
                Id = "bending_no_triangles_null_001",
                Positions = P((0, 0, 0), (1, 0, 0)),
                Attributes = new byte[] { 0x02, 0x02 },
                Edges = E((0, 1)),
                Triangles = Array.Empty<int3>(),
                Note = "TriangleCount zero returns null rather than a success-empty ConstraintData.",
            };
        }

        private static IEnumerable<BendingRuntimeCase> BendingRuntimeCases()
        {
            yield return new BendingRuntimeCase
            {
                Id = "bending_runtime_single_fixed_sum_001",
                OrderedQuads = new[] { new int4(1, 0, 2, 3) },
                RestAngleOrVolume = new[] { 0.0f },
                SignOrVolume = new sbyte[] { 1 },
                NextPositions = FoldedPair(30.0f),
                Attributes = new byte[] { 0x01, 0x02, 0x02, 0x02 },
                Note = "One directional dihedral contributes to all scratch slots; Sum keeps Fixed vertex 0 unchanged and clears every slot.",
            };
            yield return new BendingRuntimeCase
            {
                Id = "bending_runtime_double_positive_scale_001",
                OrderedQuads = new[]
                {
                    new int4(1, 0, 2, 3),
                    new int4(1, 0, 2, 3),
                },
                RestAngleOrVolume = new[] { 1.74532926f, 164.134628f },
                SignOrVolume = new sbyte[] { -1, 100 },
                NextPositions = FoldedPair(70.0f),
                Attributes = new byte[] { 0x02, 0x02, 0x02, 0x02 },
                ScaleRatio = 1.25f,
                Note = "Bending and volume both contribute; Sum averages two fixed-point scratch records per vertex.",
            };
            yield return new BendingRuntimeCase
            {
                Id = "bending_runtime_double_negative_scale_001",
                OrderedQuads = new[]
                {
                    new int4(1, 0, 2, 3),
                    new int4(1, 0, 2, 3),
                },
                RestAngleOrVolume = new[] { 1.74532926f, 164.134628f },
                SignOrVolume = new sbyte[] { -1, 100 },
                NextPositions = FoldedPair(70.0f),
                Attributes = new byte[] { 0x02, 0x02, 0x02, 0x02 },
                ScaleRatio = 1.25f,
                NegativeScaleSign = -1.0f,
                Note = "The same records consume negativeScaleSign in both directional dihedral and volume paths.",
            };
        }

        private static float3[] FoldedPair(float degrees)
        {
            float radians = math.radians(degrees);
            return P(
                (0, 1, 0),
                (0, -math.cos(radians), -math.sin(radians)),
                (0, 0, 0),
                (1, 0, 0)
            );
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

        private static string BuildBendingJson(BendingCase bendingCase, BendingDump dump)
        {
            var text = new StringBuilder();
            text.AppendLine("{");
            Property(text, 2, "schema_version", "1");
            Property(text, 2, "case_id", Quote(bendingCase.Id));
            Property(
                text,
                2,
                "source",
                SourceJson(
                    "Runtime/Cloth/Constraints/TriangleBendingConstraint.cs::CreateData",
                    "Runtime/Utility/Data/DataUtility.cs::Pack64"
                )
            );
            Property(text, 2, "scope", Quote(bendingCase.Note));
            Property(text, 2, "comparison", BendingComparisonJson());
            Property(text, 2, "input", BendingInputJson(bendingCase));
            Property(text, 2, "expected", BendingExpectedJson(dump), false);
            text.AppendLine("}");
            return text.ToString();
        }

        private static string BuildBendingRuntimeJson(
            BendingRuntimeCase runtimeCase,
            BendingRuntimeDump dump
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
                SourceJson(
                    "Runtime/Cloth/Constraints/TriangleBendingConstraint.cs::SolverConstraint",
                    "Runtime/Cloth/Constraints/TriangleBendingConstraint.cs::SumConstraint"
                )
            );
            Property(text, 2, "scope", Quote(runtimeCase.Note));
            Property(text, 2, "comparison", BendingRuntimeComparisonJson());
            Property(text, 2, "input", BendingRuntimeInputJson(runtimeCase));
            Property(text, 2, "expected", BendingRuntimeExpectedJson(dump), false);
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

        private static string BendingComparisonJson()
        {
            var text = new StringBuilder();
            text.AppendLine("{");
            Property(text, 4, "float_abs_tolerance", "1e-5");
            Property(text, 4, "float_rel_tolerance", "1e-6");
            Property(text, 4, "raw_order", Quote("ordered and role-sensitive"));
            Property(
                text,
                4,
                "canonical_membership",
                Quote("diagnostic only; never sorts output quads"),
                false
            );
            text.Append("  }");
            return text.ToString();
        }

        private static string BendingRuntimeComparisonJson()
        {
            var text = new StringBuilder();
            text.AppendLine("{");
            Property(text, 4, "float_abs_tolerance", "2e-5");
            Property(text, 4, "float_rel_tolerance", "1e-6");
            Property(text, 4, "fixed_point_scratch", Quote("raw int components before Sum"), false);
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

        private static string BendingInputJson(BendingCase bendingCase)
        {
            var text = new StringBuilder();
            text.AppendLine("{");
            Property(text, 4, "setup_type", Quote("mesh_cloth"));
            Property(text, 4, "local_positions", ArrayJson(bendingCase.Positions, Vector3Json));
            Property(
                text,
                4,
                "vertex_attributes",
                NumberArray(bendingCase.Attributes.Select(value => (int)value))
            );
            Property(text, 4, "edges", ArrayJson(bendingCase.Edges, Int2Json));
            Property(text, 4, "triangles", ArrayJson(bendingCase.Triangles, Int3Json));
            Property(
                text,
                4,
                "init_local_to_world_columns",
                Matrix4x4ColumnsJson(bendingCase.InitLocalToWorld),
                false
            );
            text.Append("  }");
            return text.ToString();
        }

        private static string BendingRuntimeInputJson(BendingRuntimeCase runtimeCase)
        {
            var text = new StringBuilder();
            text.AppendLine("{");
            Property(text, 4, "setup_type", Quote("mesh_cloth"));
            Property(text, 4, "ordered_quads", ArrayJson(runtimeCase.OrderedQuads, Int4Json));
            Property(
                text,
                4,
                "rest_angle_or_volume",
                ArrayJson(runtimeCase.RestAngleOrVolume, FloatJson)
            );
            Property(
                text,
                4,
                "sign_or_volume",
                NumberArray(runtimeCase.SignOrVolume.Select(value => (int)value))
            );
            Property(text, 4, "next_positions", ArrayJson(runtimeCase.NextPositions, Vector3Json));
            Property(
                text,
                4,
                "vertex_attributes",
                NumberArray(runtimeCase.Attributes.Select(value => (int)value))
            );
            Property(text, 4, "depths", ArrayJson(Enumerable.Repeat(0.5f, runtimeCase.NextPositions.Length), FloatJson));
            Property(text, 4, "friction", ArrayJson(new float[runtimeCase.NextPositions.Length], FloatJson));
            Property(text, 4, "stiffness", "1");
            Property(text, 4, "simulation_power_y", "1");
            Property(text, 4, "scale_ratio", FloatJson(runtimeCase.ScaleRatio));
            Property(text, 4, "negative_scale_sign", FloatJson(runtimeCase.NegativeScaleSign), false);
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

        private static string BendingExpectedJson(BendingDump dump)
        {
            var text = new StringBuilder();
            text.AppendLine("{");
            Property(text, 4, "create_returned_null", dump.CreateReturnedNull ? "true" : "false");
            Property(text, 4, "raw_packed_quads", ULongArray(dump.RawPackedQuads));
            Property(text, 4, "ordered_quads", ArrayJson(dump.OrderedQuads, Int4Json));
            Property(
                text,
                4,
                "rest_angle_or_volume",
                ArrayJson(dump.RestAngleOrVolume, FloatJson)
            );
            Property(text, 4, "sign_or_volume", NumberArray(dump.SignOrVolume));
            Property(text, 4, "diagnostic_write", BendingWriteJson(dump), false);
            text.Append("  }");
            return text.ToString();
        }

        private static string BendingRuntimeExpectedJson(BendingRuntimeDump dump)
        {
            var text = new StringBuilder();
            text.AppendLine("{");
            Property(text, 4, "count_before_sum", NumberArray(dump.CountBeforeSum));
            Property(
                text,
                4,
                "vector_components_before_sum",
                NumberArray(dump.VectorComponentsBeforeSum)
            );
            Property(
                text,
                4,
                "next_positions_after_sum",
                ArrayJson(dump.NextPositionsAfterSum, Vector3Json)
            );
            Property(text, 4, "count_after_sum", NumberArray(dump.CountAfterSum));
            Property(
                text,
                4,
                "vector_after_sum",
                ArrayJson(dump.VectorAfterSum, Vector3Json),
                false
            );
            text.Append("  }");
            return text.ToString();
        }

        private static string BendingWriteJson(BendingDump dump)
        {
            var text = new StringBuilder();
            text.AppendLine("{");
            Property(text, 6, "runtime_consumed", "false");
            Property(text, 6, "write_buffer_count", dump.WriteBufferCount.ToString(CultureInfo.InvariantCulture));
            Property(text, 6, "raw_write_data", UIntArray(dump.RawWriteData));
            Property(text, 6, "raw_write_indices", UIntArray(dump.RawWriteIndices));
            Property(text, 6, "write_ranges", ArrayJson(dump.WriteRanges, Int2Json), false);
            text.Append("    }");
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

        private static string ULongArray(IEnumerable<ulong> values)
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

        private static string Matrix4x4ColumnsJson(float4x4 value)
        {
            return ArrayJson(new[] { value.c0, value.c1, value.c2, value.c3 }, Vector4Json);
        }

        private static string Int2Json(int2 value)
        {
            return $"[{value.x},{value.y}]";
        }

        private static string Int3Json(int3 value)
        {
            return $"[{value.x},{value.y},{value.z}]";
        }

        private static string Int4Json(int4 value)
        {
            return $"[{value.x},{value.y},{value.z},{value.w}]";
        }
    }
}
